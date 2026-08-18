"""Shared AgentFinding → Finding adapter for DG1 precision paths."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import make_finding
from mergecraft.findings.causality import (
    CAUSALITY_EVIDENCE_PREFIX,
    CausalityValidationError,
    causality_text,
)
from mergecraft.findings.precision_pipeline import apply_precision_pipeline

if TYPE_CHECKING:
    from mergecraft.agents.verifier import AgentFinding
    from mergecraft.analyzers.finding import Finding

_MAINTENANCE_HINTS = frozenset(
    {
        "f-string",
        "formatting",
        "typo",
        "spelling",
        "comment",
        "docstring",
        "readme",
        "style",
        "naming",
    }
)
_SECURITY_HINTS = frozenset(
    {
        "secret",
        "token",
        "credential",
        "password",
        "injection",
        "auth",
        "sql",
        "xss",
    }
)


def _contains_category_hint(text: str, hint: str) -> bool:
    """Return whether ``hint`` appears as its own token, not a substring."""
    pattern = rf"(?<![a-z0-9]){re.escape(hint.casefold())}(?![a-z0-9])"
    return re.search(pattern, text.casefold()) is not None


def infer_agent_finding_category(body: str) -> str:
    """Infer a taxonomy category for rubric normalization."""
    if any(_contains_category_hint(body, hint) for hint in _SECURITY_HINTS):
        return "Security & Privacy"
    if any(_contains_category_hint(body, hint) for hint in _MAINTENANCE_HINTS):
        return "Maintainability & Code Quality"
    return "Functional Correctness"


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
        category=infer_agent_finding_category(finding.body),
        severity=finding.severity,
        confidence="likely",
        message=finding.body,
        path=finding.path,
        start_line=int(finding.line or 1),
        end_line=int(finding.line or 1),
        source="agent",
        evidence=evidence,
    )


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
    refined = apply_precision_pipeline(
        [
            agent_finding_to_finding(coerce_agent_finding(item), rule_id=rule_id)
            for item in findings
        ],
        dedupe=dedupe,
    )
    normalized: list[Any] = []
    for draft, finding in zip(findings, refined, strict=True):
        if isinstance(draft, AgentFinding):
            normalized.append(draft.model_copy(update={"severity": finding.severity}))
        elif isinstance(draft, dict):
            row = dict(draft)
            row["severity"] = finding.severity
            normalized.append(row)
        else:
            normalized.append(draft)
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
    "infer_agent_finding_category",
    "normalize_agent_findings_via_pipeline",
]
