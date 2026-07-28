"""End-to-end catalog adapter runner (manifest → findings)."""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from loguru import logger

from mergecraft.analyzers.parse import parse_output_file
from mergecraft.analyzers.parsers import parse_output
from mergecraft.analyzers.parsers._common import resolve_repo_relative_path
from mergecraft.analyzers.provision import ProvisionError, resolve_baked_binary, resolve_with_lock
from mergecraft.analyzers.registry import filter_changed_files_for_manifest, load_catalog
from mergecraft.analyzers.resolve import AnalyzerPlan, expand_analyzer_argv, resolve_analyzer
from mergecraft.analyzers.run import run_plan
from mergecraft.analyzers.sandbox import plan_sandbox
from mergecraft.analyzers.trust import build_analyzer_env

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.finding import Finding
    from mergecraft.analyzers.manifest import AnalyzerManifest
    from mergecraft.analyzers.sandbox import SandboxContext

TrustTier = Literal["trusted", "untrusted"]


@dataclass(frozen=True, slots=True)
class AdapterRunResult:
    findings: list[Finding]
    skipped: bool = False
    skip_reason: str | None = None
    version_note: str | None = None
    config_note: str | None = None


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
    event: dict[str, object] | None = None,
) -> AnalyzerPlan:
    scoped_files = filter_changed_files_for_manifest(manifest, changed_files)
    argv = list(expand_analyzer_argv(plan.argv, repo_root=repo_root, changed_files=scoped_files))
    if manifest.id == "trufflehog":
        argv = _trufflehog_argv(argv, repo_root=repo_root, tier=tier, event=event)
    env = build_analyzer_env(tier=tier, event=event, repo_env=None)
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


def _finalize_trufflehog_findings(findings: list[Finding], *, repo_root: Path) -> list[Finding]:
    from mergecraft.analyzers.parsers.trufflehog_jsonl import _ROTATION_FIRST_REMEDIATION

    normalized: list[Finding] = []
    for finding in findings:
        remediation = finding.remediation or _ROTATION_FIRST_REMEDIATION
        if "rotate" not in remediation.casefold():
            remediation = _ROTATION_FIRST_REMEDIATION
        normalized.append(finding.model_copy(update={"remediation": remediation}))
    _ = repo_root
    return normalized


def _provision_managed_argv(
    plan: AnalyzerPlan,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
) -> AnalyzerPlan | None:
    baked = resolve_baked_binary(manifest)
    if baked is not None:
        argv = list(plan.argv)
        if argv and argv[0] == manifest.command[0]:
            argv[0] = str(baked)
        return replace(plan, argv=tuple(argv))

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


def _format_finding(
    *,
    manifest: AnalyzerManifest,
    path: str,
    line: int,
    message: str,
) -> Finding:
    from mergecraft.analyzers.finding import make_finding
    from mergecraft.analyzers.parsers._common import map_confidence, taxonomy_category

    return make_finding(
        tool=manifest.id,
        rule_id="format",
        category=taxonomy_category(manifest),
        severity=manifest.severity_map.get("warning", "Minor"),
        confidence=map_confidence(None),
        message=message,
        path=path,
        start_line=line,
        end_line=line,
        source="analyzer",
    )


def _run_ruff_format_check(
    plan: AnalyzerPlan,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    scoped_files: list[str],
    tier: TrustTier,
    sandbox_context: SandboxContext | None,
) -> list[Finding]:
    if not plan.argv:
        return []
    binary = plan.argv[0]
    format_argv = expand_analyzer_argv(
        (binary, "format", "--check", "{files}"),
        repo_root=repo_root,
        changed_files=scoped_files,
    )
    format_plan = replace(
        plan,
        manifest_id=f"{manifest.id}-format",
        argv=format_argv,
    )
    format_plan = _finalize_plan(
        format_plan,
        manifest=manifest,
        repo_root=repo_root,
        changed_files=scoped_files,
        tier=tier,
    )
    outcome = run_plan(format_plan, sandbox_context=sandbox_context)
    if outcome.ran and outcome.exit_code == 0:
        return []
    if not scoped_files:
        return []
    rel = scoped_files[0]
    return [
        _format_finding(
            manifest=manifest,
            path=rel,
            line=1,
            message="File would be reformatted by ruff format",
        )
    ]


def run_adapter(
    *,
    tool_id: str,
    repo_root: Path,
    changed_files: list[str],
    tier: TrustTier = "trusted",
) -> AdapterRunResult:
    """Run one catalog analyzer and return normalized findings."""
    repo_root = repo_root.resolve()
    manifest = _manifest_by_id(tool_id)

    plan = resolve_analyzer(manifest=manifest, repo_root=repo_root, managed_available=True)
    if plan.mode == "skip":
        logger.info("{}", plan.reason)
        return AdapterRunResult(findings=[], skipped=True, skip_reason=plan.reason)

    if plan.mode == "managed":
        provisioned = _provision_managed_argv(plan, manifest=manifest, repo_root=repo_root)
        if provisioned is None:
            reason = f"skipped {tool_id}: managed binary provisioning failed"
            return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)
        plan = provisioned

    if plan.mode in {"ci-result", "container"} or not plan.argv:
        reason = f"skipped {tool_id}: mode {plan.mode} unavailable in this environment"
        logger.info("{}", reason)
        return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)

    scoped_files = filter_changed_files_for_manifest(manifest, changed_files)
    if not scoped_files:
        reason = f"skipped {tool_id}: no changed files match detect globs"
        logger.info("{}", reason)
        return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)

    scratch_dir = repo_root / ".mergecraft" / "analyzer-scratch" / tool_id
    scratch_dir.mkdir(parents=True, exist_ok=True)
    sandbox_decision = plan_sandbox(
        manifest=manifest,
        tier=tier,
        repo_root=repo_root,
        scratch_dir=scratch_dir,
    )
    if not sandbox_decision.can_run:
        return AdapterRunResult(
            findings=[],
            skipped=True,
            skip_reason=sandbox_decision.skip_reason,
        )

    sandbox_context: SandboxContext | None = sandbox_decision.context
    plan = _finalize_plan(
        plan,
        manifest=manifest,
        repo_root=repo_root,
        changed_files=scoped_files,
        tier=tier,
    )
    outcome = run_plan(plan, sandbox_context=sandbox_context)
    if not outcome.ran or outcome.output_path is None:
        reason = outcome.output or f"skipped {tool_id}: analyzer did not run"
        return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)

    from pathlib import Path

    try:
        findings = parse_output_file(
            Path(outcome.output_path),
            manifest=manifest,
            repo_root=repo_root,
        )
        if not findings and outcome.output.strip():
            findings = parse_output(outcome.output, manifest=manifest, repo_root=repo_root)
    except (ValueError, KeyError) as exc:
        reason = f"skipped {tool_id}: failed to parse analyzer output ({exc})"
        logger.info("{}", reason)
        return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)

    if tool_id == "ruff":
        findings = [
            *findings,
            *_run_ruff_format_check(
                plan,
                manifest=manifest,
                repo_root=repo_root,
                scoped_files=scoped_files,
                tier=tier,
                sandbox_context=sandbox_context,
            ),
        ]

    if tool_id == "trufflehog":
        findings = _finalize_trufflehog_findings(findings, repo_root=repo_root)

    return AdapterRunResult(
        findings=_normalize_paths(findings, repo_root=repo_root),
        version_note=plan.version_note,
        config_note=plan.config_note,
    )


__all__ = ["AdapterRunResult", "run_adapter"]
