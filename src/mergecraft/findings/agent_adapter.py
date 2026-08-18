"""Shared AgentFinding → Finding adapter for DG1 precision paths."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.dedup import dedupe_findings
from mergecraft.analyzers.finding import make_finding
from mergecraft.findings.causality import (
    CAUSALITY_EVIDENCE_PREFIX,
    CausalityValidationError,
    causality_text,
)
from mergecraft.findings.precision_pipeline import apply_precision_pipeline
from mergecraft.findings.severity_rubric import infer_category_from_message

if TYPE_CHECKING:
    from mergecraft.agents.verifier import AgentFinding
    from mergecraft.analyzers.finding import Finding


def coerce_agent_finding(item: Any) -> AgentFinding:
    """Parse an ``AgentFinding`` or wire dict into the typed draft shape."""
    from mergecraft.agents.verifier import AgentFinding

    if isinstance(item, AgentFinding):
        return item
    if isinstance(item, dict):
        return AgentFinding.model_validate(item)
    msg = "each finding must be an object"
    raise ValueError(msg)


def agent_finding_to_finding(
    finding: AgentFinding,
    *,
    rule_id: str,
    causality: str | None = None,
) -> Finding:
    """Convert a reviewer draft into a normalized ``Finding`` for the precision pipeline."""
    evidence: list[str] = []
    if causality and causality.strip():
        evidence.append(f"{CAUSALITY_EVIDENCE_PREFIX} {causality.strip()}")
    return make_finding(
        tool="agent",
        rule_id=rule_id,
        category=infer_category_from_message(finding.body),
        severity=finding.severity,
        confidence="likely",
        message=finding.body,
        path=finding.path,
        start_line=int(finding.line or 1),
        end_line=int(finding.line or 1),
        source="agent",
        evidence=evidence,
    )


def _finding_to_agent_draft(
    finding: Finding,
    *,
    source: AgentFinding | None = None,
) -> AgentFinding:
    """Map a normalized ``Finding`` back to the agent wire shape."""
    from mergecraft.agents.verifier import AgentFinding

    if source is not None:
        return source.model_copy(update={"severity": finding.severity})

    return AgentFinding(
        path=finding.path,
        body=finding.message,
        severity=finding.severity,
        line=finding.start_line,
        fingerprint=finding.fingerprint,
    )


def _apply_row_level_precision(
    drafts: list[AgentFinding],
    *,
    rule_id: str,
) -> list[Finding]:
    """Run rubric and causality per row without changing list cardinality."""
    converted = [agent_finding_to_finding(draft, rule_id=rule_id) for draft in drafts]
    return apply_precision_pipeline(converted, dedupe=False)


def normalize_agent_findings_via_pipeline(
    findings: list[Any],
    *,
    rule_id: str,
    dedupe: bool = False,
) -> list[Any]:
    """Run the DG1 precision pipeline and map severities back onto agent rows."""
    from mergecraft.agents.verifier import AgentFinding

    if not findings:
        return []

    drafts = [coerce_agent_finding(item) for item in findings]
    refined = _apply_row_level_precision(drafts, rule_id=rule_id)

    if dedupe:
        deduped = dedupe_findings(refined)
        surviving = {id(finding) for finding in deduped}
        normalized: list[Any] = []
        for draft, finding in zip(drafts, refined, strict=True):
            if id(finding) not in surviving:
                continue
            normalized.append(_finding_to_agent_draft(finding, source=draft))
            surviving.remove(id(finding))
        return normalized

    normalized: list[Any] = []
    for draft, finding, original in zip(drafts, refined, findings, strict=True):
        if isinstance(original, AgentFinding):
            normalized.append(draft.model_copy(update={"severity": finding.severity}))
        elif isinstance(original, dict):
            row = dict(original)
            row["severity"] = finding.severity
            normalized.append(row)
        else:
            normalized.append(original)
    return normalized


def finding_for_publication_validation(
    row: dict[str, Any] | None,
    *,
    fingerprint: str,
    causality: str,
    severity: str | None = None,
) -> Finding:
    """Build a ``Finding`` for D2 validation from agent or analyzer rows."""
    from mergecraft.agents.verifier import AgentFinding
    from mergecraft.analyzers.finding import Finding

    if row is not None and "message" in row:
        finding = Finding.model_validate(row)
        if causality_text(finding) is None and causality.strip():
            evidence = list(finding.evidence)
            evidence.append(f"{CAUSALITY_EVIDENCE_PREFIX} {causality.strip()}")
            finding = finding.model_copy(update={"evidence": evidence})
        if severity:
            finding = finding.model_copy(update={"severity": severity})
        return finding

    if row is not None:
        draft = coerce_agent_finding(row)
    else:
        if not severity:
            msg = "blocking finding requires a causality field explaining why this PR caused it"
            raise CausalityValidationError(msg)
        draft = AgentFinding(
            path="",
            body="",
            severity=severity,
            fingerprint=fingerprint,
        )
    if severity:
        draft = draft.model_copy(update={"severity": severity})
    return agent_finding_to_finding(draft, rule_id="agent:confirmed", causality=causality)


__all__ = [
    "agent_finding_to_finding",
    "coerce_agent_finding",
    "finding_for_publication_validation",
    "normalize_agent_findings_via_pipeline",
]
