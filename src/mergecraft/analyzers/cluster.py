"""Cross-tool finding clustering (D12)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.evidence.merge import severity_rank
from mergecraft.review_taxonomy import FINDING_CONFIDENCES, finding_fingerprint

if TYPE_CHECKING:
    from collections.abc import Callable

_CONFIDENCE_RANK = {name: index for index, name in enumerate(FINDING_CONFIDENCES)}


def cluster_key(finding: Finding) -> str:
    """Derive a cluster key from the existing ``finding_fingerprint()`` helper (D12)."""
    fp = finding_fingerprint(path=finding.path, body=finding.message)
    return f"{finding.path}:{finding.start_line}:{fp}"


def _raise_confidence(confidence: str, steps: int = 1) -> str:
    rank = max(_CONFIDENCE_RANK.get(confidence, 0) - steps, 0)
    return FINDING_CONFIDENCES[rank]


def _confidence_rank(confidence: str) -> int:
    return _CONFIDENCE_RANK.get(confidence, len(_CONFIDENCE_RANK))


def _evidence_entry(finding: Finding) -> str:
    return f"{finding.tool}:{finding.rule_id} — {finding.message}"


def _pick_canonical_wording(members: list[Finding]) -> Finding:
    """Pick the member whose prose becomes the canonical message (D8)."""
    agent_members = [member for member in members if member.source == "agent"]
    ci_members = [member for member in members if member.source == "ci"]
    analyzer_members = [member for member in members if member.source == "analyzer"]

    if agent_members:
        return agent_members[0]
    if ci_members:
        return ci_members[0]
    return sorted(analyzer_members, key=lambda item: item.tool)[0]


def _finding_confidence_rank(finding: Finding) -> int:
    return _confidence_rank(finding.confidence)


def _strongest_member(
    members: list[Finding],
    *,
    rank: Callable[[Finding], int],
) -> Finding:
    return min(members, key=rank)


def _merge_into_canonical(members: list[Finding]) -> Finding:
    """Merge same-cluster findings into one canonical finding."""
    wording = _pick_canonical_wording(members)
    strongest_severity = _strongest_member(members, rank=severity_rank)
    strongest_confidence = _strongest_member(members, rank=_finding_confidence_rank)

    evidence: list[str] = []
    seen_evidence: set[str] = set()
    corroboration = 0
    for member in sorted(members, key=lambda item: item.tool):
        entry = _evidence_entry(member)
        if entry not in seen_evidence:
            evidence.append(entry)
            seen_evidence.add(entry)
        if member is not wording and member.source in {"analyzer", "ci"}:
            corroboration += 1

    confidence = strongest_confidence.confidence
    if corroboration:
        confidence = _raise_confidence(confidence, min(corroboration, 2))

    key = cluster_key(wording)
    return make_finding(
        tool=wording.tool,
        rule_id=wording.rule_id,
        category=wording.category,
        severity=strongest_severity.severity,
        confidence=confidence,
        message=wording.message,
        path=wording.path,
        start_line=wording.start_line,
        end_line=wording.end_line,
        source=wording.source,
        evidence=evidence,
        remediation=wording.remediation,
        autofix=wording.autofix,
        introduced_by_pr=wording.introduced_by_pr,
        cluster_id=key,
        fingerprint=wording.fingerprint,
    )


def cluster_findings(findings: list[Finding]) -> list[Finding]:
    """Group findings by cluster key; agent prose wins over analyzer duplicates (D12)."""
    buckets: dict[str, list[Finding]] = {}
    for finding in findings:
        key = cluster_key(finding)
        buckets.setdefault(key, []).append(finding)

    clustered: list[Finding] = []
    for members in buckets.values():
        clustered.append(_merge_into_canonical(members))
    return clustered


__all__ = [
    "cluster_findings",
    "cluster_key",
]
