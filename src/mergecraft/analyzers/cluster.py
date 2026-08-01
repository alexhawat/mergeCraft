"""Cross-tool finding clustering (D12)."""

from __future__ import annotations

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.review_taxonomy import FINDING_CONFIDENCES, finding_fingerprint

_CONFIDENCE_RANK = {name: index for index, name in enumerate(FINDING_CONFIDENCES)}


def cluster_key(finding: Finding) -> str:
    """Derive a cluster key from the existing ``finding_fingerprint()`` helper (D12)."""
    fp = finding_fingerprint(path=finding.path, body=finding.message)
    return f"{finding.path}:{finding.start_line}:{fp}"


def _raise_confidence(confidence: str, steps: int = 1) -> str:
    rank = max(_CONFIDENCE_RANK.get(confidence, 0) - steps, 0)
    return FINDING_CONFIDENCES[rank]


def _evidence_entry(finding: Finding) -> str:
    return f"{finding.tool}:{finding.rule_id} — {finding.message}"


def _merge_into_canonical(members: list[Finding]) -> Finding:
    """Merge same-cluster findings into one canonical finding."""
    agent_members = [member for member in members if member.source == "agent"]
    ci_members = [member for member in members if member.source == "ci"]
    analyzer_members = [member for member in members if member.source == "analyzer"]

    if agent_members:
        canonical = agent_members[0]
    elif ci_members:
        canonical = ci_members[0]
    else:
        canonical = sorted(analyzer_members, key=lambda item: item.tool)[0]

    evidence: list[str] = []
    seen_evidence: set[str] = set()
    corroboration = 0
    for member in sorted(members, key=lambda item: item.tool):
        entry = _evidence_entry(member)
        if entry not in seen_evidence:
            evidence.append(entry)
            seen_evidence.add(entry)
        if member is not canonical and member.source in {"analyzer", "ci"}:
            corroboration += 1

    confidence = canonical.confidence
    if corroboration:
        confidence = _raise_confidence(confidence, min(corroboration, 2))

    key = cluster_key(canonical)
    return make_finding(
        tool=canonical.tool,
        rule_id=canonical.rule_id,
        category=canonical.category,
        severity=canonical.severity,
        confidence=confidence,
        message=canonical.message,
        path=canonical.path,
        start_line=canonical.start_line,
        end_line=canonical.end_line,
        source=canonical.source,
        evidence=evidence,
        remediation=canonical.remediation,
        autofix=canonical.autofix,
        introduced_by_pr=canonical.introduced_by_pr,
        cluster_id=key,
        fingerprint=canonical.fingerprint,
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
