"""Policy enforcement modes mapped onto the existing approval gate (D7)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from mergecraft.agents.gates import BLOCKING_SEVERITIES
from mergecraft.analyzers.finding import Finding, make_finding

EnforcementMode = Literal["advisory", "warning", "required", "blocking"]


@dataclass(frozen=True, slots=True)
class EnforcementResult:
    """Outcome of evaluating one policy violation under an enforcement mode."""

    mode: EnforcementMode
    contributes_blocker: bool
    finding: Finding | None = None


def _gate_facing_severity(*, mode: EnforcementMode, declared: str) -> str:
    """Map a rule's declared severity to the gate-facing finding severity (D7).

    Blocking mode always emits a blocker severity so ``decide_approval`` blocks.
    Non-blocking modes cap blocking severities so policy mode — not the rule
    field alone — controls merge authority.
    """
    if mode == "blocking":
        if declared in BLOCKING_SEVERITIES:
            return declared
        return "Major"
    if declared in BLOCKING_SEVERITIES:
        return "Minor"
    return declared


def _violation_finding(*, mode: EnforcementMode, violation: dict[str, Any]) -> Finding:
    rule_id = str(violation.get("rule_id", "policy-violation"))
    path = str(violation.get("path", "."))
    message = str(violation.get("message", "policy violation"))
    declared = str(violation.get("severity", "Major"))
    severity = _gate_facing_severity(mode=mode, declared=declared)
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

    Every mode emits an observable finding. ``blocking`` promotes non-blocking
    declared severities to ``Major`` so ``decide_approval`` blocks; advisory,
    warning, and required cap blocking declared severities to ``Minor``.
    """
    finding = _violation_finding(mode=mode, violation=violation)
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
