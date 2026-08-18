"""Baseline-vs-head analyzer suppression (DG1, D3)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.finding import Finding

_DIFF_FILE_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)
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


def _normalize_path(path: str) -> str:
    text = path.strip().replace("\\", "/")
    for prefix in ("./", "a/", "b/"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text


def _changed_paths(diff_text: str) -> set[str]:
    paths: set[str] = set()
    for match in _DIFF_FILE_RE.finditer(diff_text):
        paths.add(_normalize_path(match.group(1)))
        paths.add(_normalize_path(match.group(2)))
    return paths


def _changed_line_count(diff_text: str) -> int:
    return sum(
        1
        for line in diff_text.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )


def _baseline_identity(finding: Finding) -> tuple[str, int, str]:
    return (_normalize_path(finding.path), finding.start_line, finding.rule_id)


def should_run_baseline_suppression(*, diff_text: str, base_comparison: str) -> bool:
    """Return whether an expensive base run is worth it (D3)."""
    return (
        base_comparison == "full"
        and _changed_line_count(diff_text) >= _MIN_CHANGED_LINES_FOR_BASELINE
    )


def suppress_baseline_findings(
    *,
    head_findings: list[Finding],
    base_findings: list[Finding],
    diff_text: str,
    repo_root: Path,
    base_comparison: str,
) -> SuppressionResult:
    """Suppress analyzer hits that already existed on base (D3)."""
    del repo_root  # reserved for future path-aware checks
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

    touched = _changed_paths(diff_text)
    base_by_fingerprint = {finding.fingerprint: finding for finding in base_findings}
    base_identities = {_baseline_identity(finding) for finding in base_findings}

    reported: list[Finding] = []
    suppressed: list[Finding] = []
    audit_trail: list[SuppressionAuditEntry] = []

    for finding in head_findings:
        path = _normalize_path(finding.path)
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
    "SuppressionAuditEntry",
    "SuppressionResult",
    "should_run_baseline_suppression",
    "suppress_baseline_findings",
]
