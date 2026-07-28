"""End-to-end catalog adapter runner (manifest → findings)."""

from __future__ import annotations

import platform
import sys
from dataclasses import replace
from typing import TYPE_CHECKING, Literal

from loguru import logger

from mergecraft.analyzers.parse import parse_output_file
from mergecraft.analyzers.parsers import parse_output
from mergecraft.analyzers.parsers._common import resolve_repo_relative_path
from mergecraft.analyzers.provision import ProvisionError, resolve_with_lock
from mergecraft.analyzers.registry import load_catalog
from mergecraft.analyzers.resolve import AnalyzerPlan, expand_analyzer_argv, resolve_analyzer
from mergecraft.analyzers.run import run_plan
from mergecraft.analyzers.trust import build_analyzer_env, evaluate_manifest_for_tier

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.finding import Finding
    from mergecraft.analyzers.manifest import AnalyzerManifest

TrustTier = Literal["trusted", "untrusted"]


def _provision_platform_key() -> str:
    machine = platform.machine().casefold()
    if sys.platform == "darwin":
        if machine in {"arm64", "aarch64"}:
            return "darwin-arm64"
        return "darwin-amd64"
    if machine in {"arm64", "aarch64"}:
        return "linux-arm64"
    return "linux-amd64"


def _manifest_by_id(tool_id: str) -> AnalyzerManifest:
    for manifest in load_catalog():
        if manifest.id == tool_id:
            return manifest
    msg = f"unknown analyzer id: {tool_id!r}"
    raise KeyError(msg)


def _normalize_paths(findings: list[Finding], *, repo_root: Path) -> list[Finding]:
    normalized: list[Finding] = []
    for finding in findings:
        path = resolve_repo_relative_path(finding.path, repo_root=repo_root)
        normalized.append(finding.model_copy(update={"path": path}))
    return normalized


def _finalize_plan(
    plan: AnalyzerPlan,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    changed_files: list[str],
    tier: TrustTier,
) -> AnalyzerPlan:
    argv = expand_analyzer_argv(plan.argv, repo_root=repo_root, changed_files=changed_files)
    env = build_analyzer_env(tier=tier, event=None, repo_env=None)
    return replace(plan, argv=argv, cwd=repo_root, env=env)


def _provision_managed_argv(
    plan: AnalyzerPlan,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
) -> AnalyzerPlan | None:
    platform_key = _provision_platform_key()
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


def run_adapter(
    *,
    tool_id: str,
    repo_root: Path,
    changed_files: list[str],
    tier: TrustTier = "trusted",
) -> list[Finding]:
    """Run one catalog analyzer and return normalized findings."""
    repo_root = repo_root.resolve()
    manifest = _manifest_by_id(tool_id)
    decision = evaluate_manifest_for_tier(manifest=manifest, tier=tier)
    if decision.skipped:
        return []

    plan = resolve_analyzer(manifest=manifest, repo_root=repo_root, managed_available=True)
    if plan.mode == "skip":
        logger.info("{}", plan.reason)
        return []

    if plan.mode == "managed":
        provisioned = _provision_managed_argv(plan, manifest=manifest, repo_root=repo_root)
        if provisioned is None:
            return []
        plan = provisioned

    if plan.mode in {"ci-result", "container"} or not plan.argv:
        logger.info("adapter {} unavailable in mode {}", tool_id, plan.mode)
        return []

    plan = _finalize_plan(
        plan,
        manifest=manifest,
        repo_root=repo_root,
        changed_files=changed_files,
        tier=tier,
    )
    outcome = run_plan(plan)
    if not outcome.ran or outcome.output_path is None:
        return []

    from pathlib import Path

    findings = parse_output_file(
        Path(outcome.output_path),
        manifest=manifest,
        repo_root=repo_root,
    )
    if not findings and outcome.output.strip():
        findings = parse_output(outcome.output, manifest=manifest, repo_root=repo_root)
    return _normalize_paths(findings, repo_root=repo_root)


__all__ = ["run_adapter"]
