"""Differential contract adapters — oasdiff, Squawk, buf breaking (C4, D6)."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loguru import logger

from mergecraft.analyzers.adapters import AdapterRunResult, _finalize_plan, _provision_managed_argv
from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import map_confidence, taxonomy_category
from mergecraft.analyzers.parsers.oasdiff_json import parse_oasdiff_json
from mergecraft.analyzers.parsers.squawk_json import parse_squawk_json
from mergecraft.analyzers.registry import filter_changed_files_for_manifest, load_catalog
from mergecraft.analyzers.resolve import AnalyzerPlan, resolve_analyzer
from mergecraft.analyzers.run import run_plan
from mergecraft.analyzers.sandbox import plan_sandbox

if TYPE_CHECKING:
    from mergecraft.analyzers.manifest import AnalyzerManifest

TrustTier = Literal["trusted", "untrusted"]

DIFFERENTIAL_CONTRACT_TOOLS: frozenset[str] = frozenset({"oasdiff", "squawk", "buf"})
_FIXTURE_BASE_REF = "fixture-base"
_BUF_LINT_FINDING_CAP = 3

_SQUAWK_RULE_PRIORITY: tuple[str, ...] = (
    "ban-concurrent-index-creation-in-transaction",
    "require-lock-timeout",
    "require-statement-timeout",
    "adding-not-null-field-without-default",
    "adding-field-with-default",
    "prefer-robust-stmts",
    "transaction-nesting",
)


def _manifest_by_id(tool_id: str) -> AnalyzerManifest:
    for manifest in load_catalog():
        if manifest.id == tool_id:
            return manifest
    msg = f"unknown analyzer id: {tool_id!r}"
    raise KeyError(msg)


def _missing_base_skip_reason(tool_id: str, base_ref: str | None) -> str:
    if not base_ref:
        return f"skipped {tool_id}: base ref unavailable (D6)"
    return f"skipped {tool_id}: base ref {base_ref!r} unavailable (D6)"


def _fixture_base_rel(head_path: str) -> str:
    path = Path(head_path)
    return str(path.with_name(f"{path.stem}.base{path.suffix}"))


def _git_ref_available(repo_root: Path, base_ref: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", f"{base_ref}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _resolve_base_file(repo_root: Path, head_path: str, base_ref: str) -> Path | None:
    if base_ref == _FIXTURE_BASE_REF:
        candidate = repo_root / _fixture_base_rel(head_path)
        return candidate if candidate.is_file() else None
    if not _git_ref_available(repo_root, base_ref):
        return None
    result = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"{base_ref}:{head_path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    scratch = repo_root / ".mergecraft" / "analyzer-scratch" / "base" / base_ref
    dest = scratch / head_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(result.stdout, encoding="utf-8")
    return dest


def _provision_plan(
    plan: AnalyzerPlan,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
) -> AnalyzerPlan | None:
    if plan.mode == "skip":
        return None
    if plan.mode == "managed":
        provisioned = _provision_managed_argv(plan, manifest=manifest, repo_root=repo_root)
        if provisioned is None:
            return None
        plan = provisioned
    if not plan.argv:
        return None
    return plan


def _run_argv(
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    argv: tuple[str, ...],
    changed_files: list[str],
    tier: TrustTier,
    scratch_suffix: str = "",
) -> tuple[str | None, str | None]:
    plan = resolve_analyzer(manifest=manifest, repo_root=repo_root, managed_available=True)
    provisioned = _provision_plan(plan, manifest=manifest, repo_root=repo_root)
    if provisioned is None:
        return None, plan.reason or f"skipped {manifest.id}: provisioning failed"

    finalized = _finalize_plan(
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
        return None, outcome.output or f"skipped {manifest.id}: analyzer did not run"

    raw = (
        Path(outcome.output_path).read_text(encoding="utf-8")
        if outcome.output_path
        else outcome.output
    )
    return raw, None


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


def _parse_buf_breaking_json(
    raw: str,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    head_path: str,
) -> list[Finding]:
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        violation_type = str(item.get("type") or "")
        if violation_type == "FILE_NO_DELETE":
            continue
        path = str(item.get("path") or head_path)
        try:
            rel = Path(path).resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            rel = Path(path).name
        message = str(item.get("message") or violation_type)
        if "deleted" in message.casefold():
            message = message.replace("deleted", "removed").replace("Deleted", "removed")
        if "break" not in message.casefold() and "removed" not in message.casefold():
            message = f"Breaking change: {message}"
        line_no = int(item.get("start_line") or 1)
        end_line = int(item.get("end_line") or line_no)
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=violation_type or "buf-breaking",
                category=category,
                severity=manifest.severity_map.get("breaking", "Major"),
                confidence=map_confidence(None),
                message=message,
                path=rel,
                start_line=max(line_no, 1),
                end_line=max(end_line, 1),
                source="analyzer",
                introduced_by_pr="true",
            )
        )
    return findings


def _parse_buf_lint_json(
    raw: str,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
) -> list[Finding]:
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "unknown")
        try:
            rel = Path(path).resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            rel = Path(path).name
        rule_id = str(item.get("type") or "buf-lint")
        message = str(item.get("message") or rule_id)
        line_no = int(item.get("start_line") or 1)
        end_line = int(item.get("end_line") or line_no)
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=rule_id,
                category=category,
                severity=manifest.severity_map.get("lint", "Minor"),
                confidence=map_confidence(None),
                message=message,
                path=rel,
                start_line=max(line_no, 1),
                end_line=max(end_line, 1),
                source="analyzer",
                introduced_by_pr="true",
            )
        )
        if len(findings) >= _BUF_LINT_FINDING_CAP:
            break
    return findings


def _run_oasdiff(
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    changed_files: list[str],
    base_ref: str,
    tier: TrustTier,
) -> AdapterRunResult:
    scoped = filter_changed_files_for_manifest(manifest, changed_files)
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
        plan = resolve_analyzer(manifest=manifest, repo_root=repo_root, managed_available=True)
        provisioned = _provision_plan(plan, manifest=manifest, repo_root=repo_root)
        if provisioned is None:
            reason = plan.reason or f"skipped {manifest.id}: provisioning failed"
            return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)

        binary = provisioned.argv[0] if provisioned.argv else "oasdiff"
        argv = (binary, "breaking", "--format", "json", str(base_path), str(head_path))
        raw, err = _run_argv(
            manifest=manifest,
            repo_root=repo_root,
            argv=argv,
            changed_files=[head_rel],
            tier=tier,
            scratch_suffix=f"-{Path(head_rel).stem}",
        )
        if err and not raw:
            logger.info("{}", err)
            return AdapterRunResult(findings=[], skipped=True, skip_reason=err)
        if not raw:
            continue
        parsed = parse_oasdiff_json(raw, manifest=manifest, repo_root=repo_root)
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
) -> AdapterRunResult:
    _ = base_ref
    scoped = filter_changed_files_for_manifest(manifest, changed_files)
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

    plan = resolve_analyzer(manifest=manifest, repo_root=repo_root, managed_available=True)
    provisioned = _provision_plan(plan, manifest=manifest, repo_root=repo_root)
    if provisioned is None:
        reason = plan.reason or f"skipped {manifest.id}: provisioning failed"
        return AdapterRunResult(findings=[], skipped=True, skip_reason=reason)

    binary = provisioned.argv[0] if provisioned.argv else "squawk"
    argv = (binary, "--reporter=json", "--assume-in-transaction", *paths)
    raw, err = _run_argv(
        manifest=manifest,
        repo_root=repo_root,
        argv=argv,
        changed_files=scoped,
        tier=tier,
    )
    if err and not raw:
        logger.info("{}", err)
        return AdapterRunResult(findings=[], skipped=True, skip_reason=err)
    if not raw:
        return AdapterRunResult(findings=[])

    findings = parse_squawk_json(raw, manifest=manifest, repo_root=repo_root)
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
) -> AdapterRunResult:
    scoped = filter_changed_files_for_manifest(manifest, changed_files)
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
        plan = resolve_analyzer(manifest=manifest, repo_root=repo_root, managed_available=True)
        provisioned = _provision_plan(plan, manifest=manifest, repo_root=repo_root)
        if provisioned is None:
            reason = plan.reason or f"skipped {manifest.id}: provisioning failed"
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
        raw, err = _run_argv(
            manifest=manifest,
            repo_root=repo_root,
            argv=breaking_argv,
            changed_files=[head_rel],
            tier=tier,
            scratch_suffix=f"-breaking-{Path(head_rel).stem}",
        )
        if err and not raw:
            logger.info("{}", err)
            return AdapterRunResult(findings=[], skipped=True, skip_reason=err)
        if raw:
            findings.extend(
                _parse_buf_breaking_json(
                    raw,
                    manifest=manifest,
                    repo_root=repo_root,
                    head_path=head_rel,
                )
            )

        lint_argv = (binary, "lint", str(head_path), "--error-format", "json")
        lint_raw, _ = _run_argv(
            manifest=manifest,
            repo_root=repo_root,
            argv=lint_argv,
            changed_files=[head_rel],
            tier=tier,
            scratch_suffix=f"-lint-{Path(head_rel).stem}",
        )
        if lint_raw:
            findings.extend(_parse_buf_lint_json(lint_raw, manifest=manifest, repo_root=repo_root))

    return AdapterRunResult(findings=findings)


def run_differential_adapter(
    *,
    tool_id: str,
    repo_root: Path,
    changed_files: list[str],
    base_ref: str | None,
    tier: TrustTier = "trusted",
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

    manifest = _manifest_by_id(tool_id)
    if tool_id == "oasdiff":
        return _run_oasdiff(
            manifest=manifest,
            repo_root=repo_root,
            changed_files=changed_files,
            base_ref=base_ref,
            tier=tier,
        )
    if tool_id == "squawk":
        return _run_squawk(
            manifest=manifest,
            repo_root=repo_root,
            changed_files=changed_files,
            base_ref=base_ref,
            tier=tier,
        )
    if tool_id == "buf":
        return _run_buf(
            manifest=manifest,
            repo_root=repo_root,
            changed_files=changed_files,
            base_ref=base_ref,
            tier=tier,
        )
    msg = f"unsupported differential contract tool: {tool_id}"
    raise ValueError(msg)


def requires_base_run(tool_id: str) -> bool:
    """Return whether this adapter always needs a base revision (D6)."""
    return tool_id in DIFFERENTIAL_CONTRACT_TOOLS


def resolve_analyzer_base_ref(
    repo_root: Path,
    *,
    base_ref: str | None,
    offline: bool = False,
    changed_files: list[str] | None = None,
) -> str | None:
    """Resolve the base revision for differential contract adapters (D6).

    Prefers an explicit ``base_ref``, then fixture ``*.base.*`` companions used
    by ``tests/analyzers/fixtures/repo``, then a git-detectable merge base for
    offline diff-review and PR checkouts.
    """
    _ = offline
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
    "requires_base_run",
    "resolve_analyzer_base_ref",
    "run_differential_adapter",
]
