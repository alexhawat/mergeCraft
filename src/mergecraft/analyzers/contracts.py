"""Differential contract adapters — oasdiff, Squawk, buf breaking (C4, D6)."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loguru import logger

from mergecraft.analyzers.adapters import AdapterRunResult, tool_error_result
from mergecraft.analyzers.execution import (
    ArgvRun,
    provision_resolved_plan,
    provisioning_failure_reason,
    run_argv_result,
)
from mergecraft.analyzers.parsers.buf_native import parse_buf_breaking_json, parse_buf_lint_json
from mergecraft.analyzers.parsers.oasdiff_json import parse_oasdiff_json
from mergecraft.analyzers.parsers.squawk_json import parse_squawk_json
from mergecraft.analyzers.paths import safe_repo_relative_path
from mergecraft.analyzers.provision import ProvisionError
from mergecraft.analyzers.registry import _matches_detect_patterns, get_manifest
from mergecraft.analyzers.resolve import AnalyzerPlan, resolve_analyzer
from mergecraft.utils.git_hardening import git_argv

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding
    from mergecraft.analyzers.manifest import AnalyzerManifest

TrustTier = Literal["trusted", "untrusted"]

DIFFERENTIAL_CONTRACT_TOOLS: frozenset[str] = frozenset({"oasdiff", "squawk", "buf"})
_FIXTURE_BASE_REF = "fixture-base"
# Bound on the ref-probe and ``git show`` calls; a timeout reads as "base unavailable".
_GIT_TIMEOUT_S = 30


def _scope_changed_files(manifest: AnalyzerManifest, changed_files: list[str]) -> list[str]:
    """Keep only paths matching this manifest's detect globs.

    Uses ``_matches_detect_patterns`` directly so a stale import of
    ``filter_changed_files_for_manifest`` cannot leak from tests that
    monkeypatch the registry helper while ``contracts`` is first imported.
    """
    return [path for path in changed_files if _matches_detect_patterns(path, manifest.detect.files)]


def _missing_base_skip_reason(tool_id: str, base_ref: str | None) -> str:
    if not base_ref:
        return f"skipped {tool_id}: base ref unavailable (D6)"
    return f"skipped {tool_id}: base ref {base_ref!r} unavailable (D6)"


_SQUAWK_RULE_PRIORITY: tuple[str, ...] = (
    "ban-concurrent-index-creation-in-transaction",
    "require-lock-timeout",
    "require-statement-timeout",
    "adding-not-null-field-without-default",
    "adding-field-with-default",
    "prefer-robust-stmts",
    "transaction-nesting",
)


def _fixture_base_rel(head_path: str) -> str:
    path = Path(head_path)
    return str(path.with_name(f"{path.stem}.base{path.suffix}"))


def _git_ref_available(repo_root: Path, base_ref: str) -> bool:
    try:
        result = subprocess.run(
            git_argv(["-C", str(repo_root), "rev-parse", "--verify", f"{base_ref}^{{commit}}"]),
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


def _resolve_base_file(repo_root: Path, head_path: str, base_ref: str) -> Path | None:
    if safe_repo_relative_path(repo_root, head_path) is None:
        return None
    if base_ref == _FIXTURE_BASE_REF:
        candidate = repo_root / _fixture_base_rel(head_path)
        return candidate if candidate.is_file() else None
    if not _git_ref_available(repo_root, base_ref):
        return None
    try:
        result = subprocess.run(
            git_argv(["-C", str(repo_root), "show", f"{base_ref}:{head_path}"]),
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    scratch_rel = f".mergecraft/analyzer-scratch/base/{base_ref}/{head_path}"
    dest = safe_repo_relative_path(repo_root, scratch_rel)
    if dest is None:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(result.stdout, encoding="utf-8")
    return dest


def _provision_plan(
    plan: AnalyzerPlan,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
) -> tuple[AnalyzerPlan | None, str | None]:
    try:
        return provision_resolved_plan(plan, manifest=manifest, repo_root=repo_root), None
    except ProvisionError as exc:
        return None, provisioning_failure_reason(manifest.id, exc)


def _run_argv(
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    argv: tuple[str, ...],
    changed_files: list[str],
    tier: TrustTier,
    scratch_suffix: str = "",
) -> ArgvRun:
    run = run_argv_result(
        manifest=manifest,
        repo_root=repo_root,
        argv=argv,
        changed_files=changed_files,
        tier=tier,
        scratch_suffix=scratch_suffix,
    )
    benign = manifest.benign_exit_reason(run.exit_code, run.raw or "")
    if benign is not None:
        # A declared "nothing to scan" exit is a clean run, not a tool-error.
        logger.info("{}: exit {} — {}", manifest.id, run.exit_code, benign)
        return replace(run, raw="", exit_code=0)
    return run


def _unparsable_result(tool_id: str, exc: ValueError, *, exit_code: int | None) -> AdapterRunResult:
    """Typed result for contract-tool output that does not parse (never raw bytes)."""
    if exit_code:
        logger.info("{}: output did not parse: {}", tool_id, exc)
        return tool_error_result(tool_id, exit_code)
    reason = (
        f"skipped {tool_id}: failed to parse analyzer output; unparsable analyzer output omitted"
    )
    logger.info("{}: {}", reason, exc)
    return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)


def _reported_json_rows(raw: str) -> bool:
    """True when ``raw`` carries at least one JSON-object line (buf's annotation format)."""
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            if isinstance(json.loads(stripped), dict):
                return True
        except json.JSONDecodeError:
            continue
    return False


def _collapse_squawk_findings(findings: list[Finding]) -> list[Finding]:
    by_path: dict[str, list[Finding]] = {}
    for finding in findings:
        by_path.setdefault(finding.path, []).append(finding)

    collapsed: list[Finding] = []
    for path, group in by_path.items():
        _ = path
        chosen = group[0]
        for rule in _SQUAWK_RULE_PRIORITY:
            for item in group:
                if item.rule_id == rule:
                    chosen = item
                    break
            else:
                continue
            break
        collapsed.append(chosen)
    return collapsed


def _run_oasdiff(
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    changed_files: list[str],
    base_ref: str,
    tier: TrustTier,
    allow_repo_binaries: bool = True,
) -> AdapterRunResult:
    scoped = _scope_changed_files(manifest, changed_files)
    if not scoped:
        return AdapterRunResult(
            findings=[],
            skipped=True,
            skip_reason=f"skipped {manifest.id}: no changed OpenAPI specs",
        )

    findings: list[Finding] = []
    for head_rel in scoped:
        base_path = _resolve_base_file(repo_root, head_rel, base_ref)
        if base_path is None:
            reason = _missing_base_skip_reason(manifest.id, base_ref)
            if base_ref == _FIXTURE_BASE_REF:
                reason = (
                    f"skipped {manifest.id}: base file {_fixture_base_rel(head_rel)!r} "
                    f"unavailable for ref {base_ref!r} (D6)"
                )
            return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)

        head_path = repo_root / head_rel
        plan = resolve_analyzer(
            manifest=manifest,
            repo_root=repo_root,
            managed_available=True,
            allow_repo_binaries=allow_repo_binaries,
        )
        provisioned, provision_failure = _provision_plan(
            plan, manifest=manifest, repo_root=repo_root
        )
        if provisioned is None:
            reason = (
                provision_failure or plan.reason or f"skipped {manifest.id}: provisioning failed"
            )
            return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)

        binary = provisioned.argv[0] if provisioned.argv else "oasdiff"
        argv = (binary, "breaking", "--format", "json", str(base_path), str(head_path))
        run = _run_argv(
            manifest=manifest,
            repo_root=repo_root,
            argv=argv,
            changed_files=[head_rel],
            tier=tier,
            scratch_suffix=f"-{Path(head_rel).stem}",
        )
        if run.raw is None:
            reason = run.reason or f"skipped {manifest.id}: analyzer did not run"
            logger.info("{}", reason)
            return AdapterRunResult(findings=run.findings, skipped=True, skip_reason=reason)
        if not run.raw.strip():
            if run.exit_code:
                return tool_error_result(manifest.id, run.exit_code, findings=findings)
            continue
        try:
            parsed = parse_oasdiff_json(run.raw, manifest=manifest, repo_root=repo_root)
        except ValueError as exc:
            return _unparsable_result(manifest.id, exc, exit_code=run.exit_code)
        if not parsed and run.exit_code:
            return tool_error_result(manifest.id, run.exit_code, findings=findings)
        for finding in parsed:
            findings.append(finding.model_copy(update={"path": head_rel}))
    return AdapterRunResult(findings=findings)


def _run_squawk(
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    changed_files: list[str],
    base_ref: str,
    tier: TrustTier,
    allow_repo_binaries: bool = True,
) -> AdapterRunResult:
    _ = base_ref
    scoped = _scope_changed_files(manifest, changed_files)
    if not scoped:
        return AdapterRunResult(
            findings=[],
            skipped=True,
            skip_reason=f"skipped {manifest.id}: no changed migration files",
        )

    paths = [str((repo_root / rel).resolve()) for rel in scoped if (repo_root / rel).is_file()]
    if not paths:
        return AdapterRunResult(
            findings=[],
            skipped=True,
            skip_reason=f"skipped {manifest.id}: migration paths missing on disk",
        )

    plan = resolve_analyzer(
        manifest=manifest,
        repo_root=repo_root,
        managed_available=True,
        allow_repo_binaries=allow_repo_binaries,
    )
    provisioned, provision_failure = _provision_plan(plan, manifest=manifest, repo_root=repo_root)
    if provisioned is None:
        reason = provision_failure or plan.reason or f"skipped {manifest.id}: provisioning failed"
        return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)

    binary = provisioned.argv[0] if provisioned.argv else "squawk"
    argv = (binary, "--reporter=json", "--assume-in-transaction", *paths)
    run = _run_argv(
        manifest=manifest,
        repo_root=repo_root,
        argv=argv,
        changed_files=scoped,
        tier=tier,
    )
    if run.raw is None:
        reason = run.reason or f"skipped {manifest.id}: analyzer did not run"
        logger.info("{}", reason)
        return AdapterRunResult(findings=run.findings, skipped=True, skip_reason=reason)
    if not run.raw.strip():
        if run.exit_code:
            return tool_error_result(manifest.id, run.exit_code)
        return AdapterRunResult(findings=[])

    try:
        findings = parse_squawk_json(run.raw, manifest=manifest, repo_root=repo_root)
    except ValueError as exc:
        return _unparsable_result(manifest.id, exc, exit_code=run.exit_code)
    if not findings and run.exit_code:
        return tool_error_result(manifest.id, run.exit_code)
    normalized: list[Finding] = []
    for finding in findings:
        try:
            rel = Path(finding.path).resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            rel = finding.path
        normalized.append(finding.model_copy(update={"path": rel}))
    return AdapterRunResult(findings=_collapse_squawk_findings(normalized))


def _run_buf(
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    changed_files: list[str],
    base_ref: str,
    tier: TrustTier,
    allow_repo_binaries: bool = True,
) -> AdapterRunResult:
    scoped = _scope_changed_files(manifest, changed_files)
    if not scoped:
        return AdapterRunResult(
            findings=[],
            skipped=True,
            skip_reason=f"skipped {manifest.id}: no changed proto files",
        )

    findings: list[Finding] = []
    for head_rel in scoped:
        base_path = _resolve_base_file(repo_root, head_rel, base_ref)
        if base_path is None:
            reason = _missing_base_skip_reason(manifest.id, base_ref)
            if base_ref == _FIXTURE_BASE_REF:
                reason = (
                    f"skipped {manifest.id}: base file {_fixture_base_rel(head_rel)!r} "
                    f"unavailable for ref {base_ref!r} (D6)"
                )
            return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)

        head_path = repo_root / head_rel
        plan = resolve_analyzer(
            manifest=manifest,
            repo_root=repo_root,
            managed_available=True,
            allow_repo_binaries=allow_repo_binaries,
        )
        provisioned, provision_failure = _provision_plan(
            plan, manifest=manifest, repo_root=repo_root
        )
        if provisioned is None:
            reason = (
                provision_failure or plan.reason or f"skipped {manifest.id}: provisioning failed"
            )
            return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)

        binary = provisioned.argv[0] if provisioned.argv else "buf"
        breaking_argv = (
            binary,
            "breaking",
            str(head_path),
            "--against",
            str(base_path),
            "--error-format",
            "json",
        )
        breaking = _run_argv(
            manifest=manifest,
            repo_root=repo_root,
            argv=breaking_argv,
            changed_files=[head_rel],
            tier=tier,
            scratch_suffix=f"-breaking-{Path(head_rel).stem}",
        )
        if breaking.raw is None:
            reason = breaking.reason or f"skipped {manifest.id}: analyzer did not run"
            logger.info("{}", reason)
            return AdapterRunResult(findings=breaking.findings, skipped=True, skip_reason=reason)
        # buf exits non-zero both for reported annotations and for a failed
        # build; only JSON annotation rows mean the comparison actually ran.
        if breaking.exit_code and not _reported_json_rows(breaking.raw):
            return tool_error_result(manifest.id, breaking.exit_code, findings=findings)
        findings.extend(
            parse_buf_breaking_json(
                breaking.raw,
                manifest=manifest,
                repo_root=repo_root,
                head_path=head_rel,
            )
        )

        lint_argv = (binary, "lint", str(head_path), "--error-format", "json")
        lint = _run_argv(
            manifest=manifest,
            repo_root=repo_root,
            argv=lint_argv,
            changed_files=[head_rel],
            tier=tier,
            scratch_suffix=f"-lint-{Path(head_rel).stem}",
        )
        if lint.raw is None:
            logger.info("{} lint did not run: {}", manifest.id, lint.reason)
            continue
        if lint.exit_code and not _reported_json_rows(lint.raw):
            return tool_error_result(manifest.id, lint.exit_code, findings=findings)
        findings.extend(parse_buf_lint_json(lint.raw, manifest=manifest, repo_root=repo_root))

    return AdapterRunResult(findings=findings)


def run_differential_adapter(
    *,
    tool_id: str,
    repo_root: Path,
    changed_files: list[str],
    base_ref: str | None,
    tier: TrustTier = "trusted",
    allow_repo_binaries: bool = True,
) -> AdapterRunResult:
    """Run a differential contract adapter; requires an explicit base ref (D6)."""
    repo_root = repo_root.resolve()
    if tool_id not in DIFFERENTIAL_CONTRACT_TOOLS:
        msg = f"unsupported differential contract tool: {tool_id}"
        raise ValueError(msg)

    if not base_ref:
        return AdapterRunResult(
            findings=[],
            skipped=True,
            skip_reason=_missing_base_skip_reason(tool_id, base_ref),
        )

    if tier == "untrusted" and base_ref == _FIXTURE_BASE_REF and tool_id != "squawk":
        # Companion ``*.base.*`` files live in the reviewed tree; on the untrusted
        # tier the comparison side must come from the base revision itself.
        return AdapterRunResult(
            findings=[],
            skipped=True,
            skip_reason=(
                f"skipped {tool_id}: base revision unavailable; companion base files in "
                "the reviewed tree are not used on the untrusted tier (D6)"
            ),
        )

    manifest = get_manifest(tool_id)
    if tool_id == "oasdiff":
        return _run_oasdiff(
            manifest=manifest,
            repo_root=repo_root,
            changed_files=changed_files,
            base_ref=base_ref,
            tier=tier,
            allow_repo_binaries=allow_repo_binaries,
        )
    if tool_id == "squawk":
        return _run_squawk(
            manifest=manifest,
            repo_root=repo_root,
            changed_files=changed_files,
            base_ref=base_ref,
            tier=tier,
            allow_repo_binaries=allow_repo_binaries,
        )
    if tool_id == "buf":
        return _run_buf(
            manifest=manifest,
            repo_root=repo_root,
            changed_files=changed_files,
            base_ref=base_ref,
            tier=tier,
            allow_repo_binaries=allow_repo_binaries,
        )
    msg = f"unsupported differential contract tool: {tool_id}"
    raise ValueError(msg)


def resolve_analyzer_base_ref(
    repo_root: Path,
    *,
    base_ref: str | None,
    changed_files: list[str] | None = None,
) -> str | None:
    """Resolve the base revision for differential contract adapters (D6).

    Prefers an explicit ``base_ref``, then fixture ``*.base.*`` companions used
    by ``tests/analyzers/fixtures/repo``, then a git-detectable merge base for
    offline diff-review and PR checkouts.
    """
    if base_ref:
        return base_ref
    for head_rel in changed_files or []:
        if (repo_root / _fixture_base_rel(head_rel)).is_file():
            return _FIXTURE_BASE_REF
    try:
        from mergecraft.utils.offline_diff import detect_default_base

        detected = detect_default_base(repo_root)
    except RuntimeError:
        return None
    if _git_ref_available(repo_root, detected):
        return detected
    return None


__all__ = [
    "DIFFERENTIAL_CONTRACT_TOOLS",
    "resolve_analyzer_base_ref",
    "run_differential_adapter",
]
