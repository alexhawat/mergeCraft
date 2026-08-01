"""Shared analyzer execution helpers — provision, finalize, and argv runs."""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loguru import logger

from mergecraft.analyzers.provision import ProvisionError, resolve_baked_binary, resolve_with_lock
from mergecraft.analyzers.registry import filter_changed_files_for_manifest
from mergecraft.analyzers.resolve import AnalyzerPlan, expand_analyzer_argv, resolve_analyzer
from mergecraft.analyzers.run import run_plan
from mergecraft.analyzers.sandbox import plan_sandbox
from mergecraft.analyzers.trust import build_analyzer_env

if TYPE_CHECKING:
    from mergecraft.analyzers.manifest import AnalyzerManifest

TrustTier = Literal["trusted", "untrusted"]


def provision_platform_key() -> str:
    machine = platform.machine().casefold()
    if sys.platform == "darwin":
        if machine in {"arm64", "aarch64"}:
            return "darwin-arm64"
        return "darwin-amd64"
    if machine in {"arm64", "aarch64"}:
        return "linux-arm64"
    return "linux-amd64"


def finalize_plan(
    plan: AnalyzerPlan,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    changed_files: list[str],
    tier: TrustTier,
    event: dict[str, object] | None = None,
) -> AnalyzerPlan:
    scoped_files = filter_changed_files_for_manifest(manifest, changed_files)
    argv = list(expand_analyzer_argv(plan.argv, repo_root=repo_root, changed_files=scoped_files))
    if manifest.id == "trufflehog":
        argv = _trufflehog_argv(argv, repo_root=repo_root, tier=tier, event=event)
    env = build_analyzer_env(tier=tier, event=event, repo_env=None)
    if plan.env:
        env = {**env, **plan.env}
    return replace(plan, argv=tuple(argv), cwd=repo_root, env=env)


def _trufflehog_argv(
    argv: list[str],
    *,
    repo_root: Path,
    tier: TrustTier,
    event: dict[str, object] | None,
) -> list[str]:
    from mergecraft.analyzers.config import trufflehog_verify_enabled

    filtered = [arg for arg in argv if arg not in {"--no-verification", "--verification"}]
    if trufflehog_verify_enabled(repo_root=repo_root, tier=tier, event=event):
        if "--verification" not in filtered:
            filtered.append("--verification")
    elif "--no-verification" not in filtered:
        filtered.append("--no-verification")
    return filtered


def provision_managed_argv(
    plan: AnalyzerPlan,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
) -> AnalyzerPlan | None:
    if manifest.id == "semgrep":
        from mergecraft.analyzers.pattern import provision_pip_script

        cache_dir = repo_root / ".mergecraft" / "analyzer-cache"
        try:
            script = provision_pip_script(
                package="semgrep",
                version=manifest.version,
                script="semgrep",
                cache_dir=cache_dir,
            )
        except OSError as exc:
            logger.info("{}", exc)
            return None
        argv = list(plan.argv)
        if argv and argv[0] == manifest.command[0]:
            argv[0] = str(script)
        bin_dir = str(script.parent)
        install_root = str(script.parent.parent)
        env = dict(plan.env or {})
        system_path = os.environ.get("PATH", "")
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH') or system_path}"
        prefix = env.get("PYTHONPATH")
        env["PYTHONPATH"] = f"{install_root}{os.pathsep}{prefix}" if prefix else install_root
        return replace(plan, argv=tuple(argv), env=env)

    baked = resolve_baked_binary(manifest)
    if baked is not None:
        argv = list(plan.argv)
        if argv and argv[0] == manifest.command[0]:
            argv[0] = str(baked)
        return replace(plan, argv=tuple(argv))

    platform_key = provision_platform_key()
    cache_dir = repo_root / ".mergecraft" / "analyzer-cache"
    lock_path = repo_root / ".mergecraft" / "analyzers.lock"
    try:
        result = resolve_with_lock(
            manifest=manifest,
            lock_path=lock_path,
            cache_dir=cache_dir,
            platform=platform_key,
        )
    except ProvisionError as exc:
        logger.info("{}", exc)
        return None

    argv = list(plan.argv)
    if argv and argv[0] == manifest.command[0]:
        argv[0] = str(result.resolved_path)
    return replace(plan, argv=tuple(argv))


def provision_resolved_plan(
    plan: AnalyzerPlan,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
) -> AnalyzerPlan | None:
    if plan.mode == "skip":
        return None
    if plan.mode == "managed":
        provisioned = provision_managed_argv(plan, manifest=manifest, repo_root=repo_root)
        if provisioned is None:
            return None
        plan = provisioned
    if not plan.argv:
        return None
    return plan


def run_argv(
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    argv: tuple[str, ...],
    changed_files: list[str],
    tier: TrustTier,
    scratch_suffix: str = "",
) -> tuple[str | None, str | None]:
    """Provision, sandbox, run, and return raw analyzer output."""
    plan = resolve_analyzer(manifest=manifest, repo_root=repo_root, managed_available=True)
    provisioned = provision_resolved_plan(plan, manifest=manifest, repo_root=repo_root)
    if provisioned is None:
        return None, plan.reason or f"skipped {manifest.id}: provisioning failed"

    finalized = finalize_plan(
        replace(provisioned, argv=argv, cwd=repo_root),
        manifest=manifest,
        repo_root=repo_root,
        changed_files=changed_files,
        tier=tier,
    )

    scratch = repo_root / ".mergecraft" / "analyzer-scratch" / f"{manifest.id}{scratch_suffix}"
    scratch.mkdir(parents=True, exist_ok=True)
    sandbox = plan_sandbox(
        manifest=manifest,
        tier=tier,
        repo_root=repo_root,
        scratch_dir=scratch,
    )
    if not sandbox.can_run:
        return None, sandbox.skip_reason

    outcome = run_plan(finalized, sandbox_context=sandbox.context)
    if not outcome.ran:
        return None, outcome.output

    raw = (
        Path(outcome.output_path).read_text(encoding="utf-8")
        if outcome.output_path
        else outcome.output
    )
    return raw, None


__all__ = [
    "finalize_plan",
    "provision_managed_argv",
    "provision_platform_key",
    "provision_resolved_plan",
    "run_argv",
]
