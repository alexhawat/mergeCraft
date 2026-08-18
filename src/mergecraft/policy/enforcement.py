"""Policy enforcement modes mapped onto the existing approval gate (D7)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from mergecraft.analyzers.finding import Finding, make_finding

EnforcementMode = Literal["advisory", "warning", "required", "blocking"]


@dataclass(frozen=True, slots=True)
class EnforcementResult:
    """Outcome of evaluating one policy violation under an enforcement mode."""

    mode: EnforcementMode
    contributes_blocker: bool
    finding: Finding | None = None


def _violation_finding(violation: dict[str, Any]) -> Finding:
    rule_id = str(violation.get("rule_id", "policy-violation"))
    path = str(violation.get("path", "."))
    message = str(violation.get("message", "policy violation"))
    severity = str(violation.get("severity", "Major"))
    return make_finding(
        tool="policy",
        rule_id=rule_id,
        category="Security & Privacy",
        severity=severity,
        confidence="certain",
        message=message,
        path=path,
        start_line=1,
        end_line=1,
        source="analyzer",
    )


def evaluate_enforcement(
    mode: EnforcementMode,
    *,
    violation: dict[str, Any],
) -> EnforcementResult:
    """Map a policy violation to a gate-facing enforcement outcome (D7).

    Every mode emits an observable finding. Only ``blocking`` sets
    ``contributes_blocker``; advisory, warning, and required violations are
    non-blocking comments that preserve the rule's declared severity.
    """
    finding = _violation_finding(violation)
    contributes_blocker = mode == "blocking"
    return EnforcementResult(
        mode=mode,
        contributes_blocker=contributes_blocker,
        finding=finding,
    )


__all__ = [
    "EnforcementMode",
    "EnforcementResult",
    "evaluate_enforcement",
]
