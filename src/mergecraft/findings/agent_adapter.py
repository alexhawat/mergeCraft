"""Shared AgentFinding → Finding adapter for DG1 precision paths."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import make_finding
from mergecraft.findings.causality import CAUSALITY_EVIDENCE_PREFIX

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


def infer_agent_finding_category(body: str) -> str:
    """Infer a taxonomy category for rubric normalization."""
    text = body.casefold()
    if any(hint in text for hint in _SECURITY_HINTS):
        return "Security & Privacy"
    if any(hint in text for hint in _MAINTENANCE_HINTS):
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


__all__ = [
    "agent_finding_to_finding",
    "coerce_agent_finding",
    "infer_agent_finding_category",
]
