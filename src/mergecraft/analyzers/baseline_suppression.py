"""Baseline-vs-head analyzer suppression (DG1, D3)."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loguru import logger

from mergecraft.analyzers.scope import DiffScope, changed_paths_from_scope, parse_diff_scope
from mergecraft.review_policy.paths import normalize_repo_path

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding
    from mergecraft.analyzers.manifest import AnalyzerManifest

TrustTier = Literal["trusted", "untrusted"]

_MIN_CHANGED_LINES_FOR_BASELINE = 12


@dataclass(frozen=True, slots=True)
class SuppressionAuditEntry:
    """One auditable suppression decision (convention 7)."""

    fingerprint: str
    decision: Literal["suppressed", "reported"]
    reason: str


@dataclass(slots=True)
class SuppressionResult:
    """Findings after baseline suppression with an audit trail."""

    reported: list[Finding] = field(default_factory=list)
    suppressed: list[Finding] = field(default_factory=list)
    audit_trail: list[SuppressionAuditEntry] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BaseCollectionResult:
    """Outcome of running analyzers at the base ref."""

    findings: list[Finding]
    collected: bool


def _touched_paths(diff_text: str, *, scope: DiffScope | None = None) -> set[str]:
    parsed = scope if scope is not None else parse_diff_scope(diff_text)
    return {normalize_repo_path(path) for path in changed_paths_from_scope(parsed)}


def _changed_line_count(diff_text: str) -> int:
    return sum(
        1
        for line in diff_text.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )


def _baseline_identity(finding: Finding) -> tuple[str, int, str]:
    return (normalize_repo_path(finding.path), finding.start_line, finding.rule_id)


def should_run_baseline_suppression(*, diff_text: str, base_comparison: str) -> bool:
    """Return whether an expensive base run is worth it (D3)."""
    return (
        base_comparison == "full"
        and _changed_line_count(diff_text) >= _MIN_CHANGED_LINES_FOR_BASELINE
    )


def _checkout_base_worktree(repo_root: Path, base_ref: str) -> Path | None:
    worktree = Path(tempfile.mkdtemp(prefix="mergecraft-base-"))
    result = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", "--detach", str(worktree), base_ref],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        logger.info(
            "baseline suppression: could not materialize base worktree at {}: {}",
            base_ref,
            (result.stderr or result.stdout or "").strip(),
        )
        worktree.rmdir()
        return None
    return worktree


def _remove_base_worktree(repo_root: Path, worktree: Path) -> None:
    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(worktree)],
        capture_output=True,
        text=True,
        check=False,
    )


def collect_base_analyzer_findings(
    *,
    repo_root: Path,
    manifests: list[AnalyzerManifest],
    changed_files: list[str],
    head_findings: list[Finding],
    tier: TrustTier = "trusted",
    base_ref: str | None = None,
    offline: bool = False,
    allow_repo_binaries: bool = True,
) -> BaseCollectionResult:
    """Run the same enabled analyzers at ``base_ref`` and return their findings."""
    from mergecraft.analyzers.adapters import run_adapter
    from mergecraft.analyzers.contracts import resolve_analyzer_base_ref

    resolved = resolve_analyzer_base_ref(
        repo_root,
        base_ref=base_ref,
        offline=offline,
        changed_files=changed_files,
    )
    if not resolved:
        logger.info("baseline suppression: base ref unavailable — skipping base collection")
        return BaseCollectionResult(findings=[], collected=False)

    scan_files = list(
        dict.fromkeys(
            [*changed_files, *(normalize_repo_path(finding.path) for finding in head_findings)]
        )
    )
    worktree = _checkout_base_worktree(repo_root, resolved)
    if worktree is None:
        return BaseCollectionResult(findings=[], collected=False)

    base_findings: list[Finding] = []
    any_succeeded = False
    try:
        for manifest in manifests:
            try:
                result = run_adapter(
                    tool_id=manifest.id,
                    repo_root=worktree,
                    changed_files=scan_files,
                    tier=tier,
                    base_ref=resolved,
                    offline=offline,
                    allow_repo_binaries=allow_repo_binaries,
                )
            except (KeyError, OSError, ValueError) as exc:
                logger.info(
                    "baseline suppression: analyzer {} unavailable at base: {}",
                    manifest.id,
                    exc,
                )
                continue
            if result.skipped:
                continue
            any_succeeded = True
            base_findings.extend(result.findings)
    finally:
        _remove_base_worktree(repo_root, worktree)
    return BaseCollectionResult(findings=base_findings, collected=any_succeeded)


def log_suppression_audit(audit_trail: list[SuppressionAuditEntry]) -> None:
    """Emit one auditable log line per suppression decision (convention 7)."""
    for entry in audit_trail:
        logger.info(
            "baseline suppression: decision={} fingerprint={} reason={}",
            entry.decision,
            entry.fingerprint,
            entry.reason,
        )


def suppress_baseline_findings(
    *,
    head_findings: list[Finding],
    base_findings: list[Finding],
    diff_text: str,
    base_comparison: str,
    scope: DiffScope | None = None,
) -> SuppressionResult:
    """Suppress analyzer hits that already existed on base (D3)."""
    if base_comparison != "full":
        return SuppressionResult(
            reported=list(head_findings),
            audit_trail=[
                SuppressionAuditEntry(
                    fingerprint=finding.fingerprint,
                    decision="reported",
                    reason="baseline suppression disabled",
                )
                for finding in head_findings
            ],
        )

    touched = _touched_paths(diff_text, scope=scope)
    base_by_fingerprint = {finding.fingerprint: finding for finding in base_findings}
    base_identities = {_baseline_identity(finding) for finding in base_findings}

    reported: list[Finding] = []
    suppressed: list[Finding] = []
    audit_trail: list[SuppressionAuditEntry] = []

    for finding in head_findings:
        path = normalize_repo_path(finding.path)
        preexisting = (
            finding.fingerprint in base_by_fingerprint
            or _baseline_identity(finding) in base_identities
        )
        if preexisting and path not in touched:
            suppressed.append(finding)
            audit_trail.append(
                SuppressionAuditEntry(
                    fingerprint=finding.fingerprint,
                    decision="suppressed",
                    reason="pre-existing analyzer hit on untouched line",
                )
            )
            continue
        reported.append(finding)
        audit_trail.append(
            SuppressionAuditEntry(
                fingerprint=finding.fingerprint,
                decision="reported",
                reason="new hit or touched file",
            )
        )

    return SuppressionResult(reported=reported, suppressed=suppressed, audit_trail=audit_trail)


__all__ = [
    "BaseCollectionResult",
    "SuppressionAuditEntry",
    "SuppressionResult",
    "collect_base_analyzer_findings",
    "log_suppression_audit",
    "should_run_baseline_suppression",
    "suppress_baseline_findings",
]
