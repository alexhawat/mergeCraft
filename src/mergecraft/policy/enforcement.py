"""Policy enforcement modes mapped onto the existing approval gate (D7)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mergecraft.agents.gates import BLOCKING_SEVERITIES
from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.policy.evidence import evaluate_rule_evidence
from mergecraft.policy.schema import EnforcementModeLiteral

EnforcementMode = EnforcementModeLiteral


@dataclass(frozen=True, slots=True)
class EnforcementResult:
    """Outcome of evaluating one policy violation under an enforcement mode."""

    mode: EnforcementMode
    contributes_blocker: bool
    finding: Finding | None = None


def _rule_from_violation(violation: dict[str, Any]) -> dict[str, Any] | None:
    rule = violation.get("rule")
    if isinstance(rule, dict):
        return rule
    return None


def _required_evidence_keys(rule: dict[str, Any]) -> list[str]:
    evidence = rule.get("evidence")
    if not isinstance(evidence, dict):
        return []
    required = evidence.get("required")
    if not isinstance(required, list):
        return []
    return [str(item) for item in required]


def _evidence_cleared(violation: dict[str, Any]) -> bool:
    """Return whether declared evidence requirements are satisfied for this violation."""
    rule = _rule_from_violation(violation)
    if rule is None:
        return True
    if not _required_evidence_keys(rule):
        return True
    available = violation.get("available_evidence")
    if not isinstance(available, dict):
        available = {}
    return evaluate_rule_evidence(rule, available_evidence=available).status == "satisfied"


def _gate_facing_severity(
    *,
    mode: EnforcementMode,
    declared: str,
    violation: dict[str, Any],
) -> str:
    """Map a rule's declared severity to the gate-facing finding severity (D7, D12).

    ``advisory`` caps blocking severities visibly to ``Trivial``. ``warning`` and
    ``required`` preserve the declared value when evidence clears a required rule.
    ``required`` downgrades ``Critical`` to ``Major`` when evidence is not cleared
    so the mode stays distinguishable from ``blocking`` at the same declared
    severity. ``blocking`` preserves declared severity and no longer promotes
    ``Minor`` to ``Major``.
    """
    if mode == "advisory" and declared in BLOCKING_SEVERITIES:
        return "Trivial"
    if mode == "required" and not _evidence_cleared(violation) and declared == "Critical":
        return "Major"
    return declared


def _violation_finding(*, mode: EnforcementMode, violation: dict[str, Any]) -> Finding:
    rule_id = str(violation.get("rule_id", "policy-violation"))
    path = str(violation.get("path", "."))
    message = str(violation.get("message", "policy violation"))
    declared = str(violation.get("severity", "Major"))
    severity = _gate_facing_severity(mode=mode, declared=declared, violation=violation)
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


def _contributes_blocker(*, mode: EnforcementMode, violation: dict[str, Any]) -> bool:
    if mode == "blocking":
        return True
    if mode == "required":
        return not _evidence_cleared(violation)
    return False


def evaluate_enforcement(
    mode: EnforcementMode,
    *,
    violation: dict[str, Any],
) -> EnforcementResult:
    """Map a policy violation to a gate-facing enforcement outcome (D7, D12).

    ``blocking`` always contributes a blocker at the declared severity (without
    promoting ``Minor`` to ``Major``). ``required`` consults ``policy.evidence``
    and contributes a blocker until declared evidence is present. ``warning`` and
    ``advisory`` never contribute blockers; ``advisory`` caps blocking severities
    to ``Trivial`` visibly.
    """
    finding = _violation_finding(mode=mode, violation=violation)
    contributes_blocker = _contributes_blocker(mode=mode, violation=violation)
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
