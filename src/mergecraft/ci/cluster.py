"""Root-cause clustering for normalized CI failures (K2.1 / K2.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.analyzers.finding import Finding, IntroducedByPr, make_finding
from mergecraft.ci.paths import failure_line, primary_failure_path

if TYPE_CHECKING:
    from mergecraft.ci.types import NormalizedFailure

_CI_CATEGORY = "Stability & Availability"
_CI_TOOL = "ci"


def cluster_key(item: NormalizedFailure) -> str:
    """Cluster by failure fingerprint, then shared command."""
    return f"{item['failure_fingerprint']}:{item['command'].strip()}"


def _failure_message(item: NormalizedFailure) -> str:
    excerpt = item["log_excerpt"].strip()
    if excerpt:
        for line in reversed(excerpt.splitlines()):
            stripped = line.strip()
            if any(
                token in stripped
                for token in ("FAILED", "AssertionError", "Error", "make: ***", "##[error]")
            ):
                return stripped[:240]
        tail = excerpt.splitlines()[-1].strip()
        if tail:
            return tail[:240]
    command = item["command"].strip()
    if command:
        return f"{command} exited with code {item['exit_code']}"
    return f"CI step {item['step']} failed with exit code {item['exit_code']}"


def _evidence_entry(item: NormalizedFailure) -> str:
    return f"{item['job']}:{item['step']}"


def failure_to_finding(
    item: NormalizedFailure,
    *,
    evidence: list[str] | None = None,
    introduced_by_pr: IntroducedByPr = "unknown",
    severity: str = "Major",
) -> Finding:
    """Convert one normalized failure into a ``source: ci`` finding for cross-source clustering."""
    path = primary_failure_path(item["log_excerpt"])
    line = failure_line(item["log_excerpt"], path=path) if path != "ci/pipeline" else 1
    message = _failure_message(item)
    return make_finding(
        tool=_CI_TOOL,
        rule_id=item["failure_fingerprint"],
        category=_CI_CATEGORY,
        severity=severity,
        confidence="likely",
        message=message,
        path=path,
        start_line=line,
        end_line=line,
        source="ci",
        evidence=evidence or [_evidence_entry(item)],
        introduced_by_pr=introduced_by_pr,
        fingerprint=item["failure_fingerprint"],
    )


def cluster_failures(failures: list[NormalizedFailure]) -> list[Finding]:
    """Group failures by root cause and publish one finding per cluster."""
    buckets: dict[str, list[NormalizedFailure]] = {}
    for item in failures:
        buckets.setdefault(cluster_key(item), []).append(item)

    clustered: list[Finding] = []
    for members in buckets.values():
        representative = members[0]
        evidence: list[str] = []
        seen: set[str] = set()
        for member in members:
            entry = _evidence_entry(member)
            if entry not in seen:
                evidence.append(entry)
                seen.add(entry)
        clustered.append(failure_to_finding(representative, evidence=evidence))
    return clustered


__all__ = [
    "cluster_failures",
    "cluster_key",
    "failure_to_finding",
]
