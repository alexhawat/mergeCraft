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
        return False
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
    """Map a rule's declared severity to the gate-facing finding severity (D7, D12, #554).

    The gate-facing severity is the single authority for whether a violation
    blocks: ``decide_approval`` reads ``Finding.severity`` and nothing else, so
    every mode encodes its blocking intent here rather than in a parallel flag.

    ``advisory`` caps blocking severities to ``Trivial``. ``warning`` caps them
    to ``Minor`` — loud enough to stay visible, and distinct from ``advisory``,
    but below the gate. ``required`` preserves the declared value when the rule
    carries no evidence keys, caps blocking severities to ``Trivial`` once
    declared evidence is satisfied so a cleared obligation cannot block, and
    downgrades ``Critical`` to ``Major`` while evidence is outstanding so the
    mode stays distinguishable from ``blocking``. ``blocking`` floors a
    non-blocking declared severity up to ``Major`` so a blocking rule actually
    blocks (#554; reverses MCB-12, which left the intent in an unread flag).

    The declared severity is preserved on the finding's ``evidence`` list
    whenever it differs, so capping never hides what the rule asked for.
    """
    if mode == "advisory" and declared in BLOCKING_SEVERITIES:
        return "Trivial"
    if mode == "warning" and declared in BLOCKING_SEVERITIES:
        return "Minor"
    if mode == "required":
        rule = _rule_from_violation(violation)
        if rule is not None and _required_evidence_keys(rule):
            if _evidence_cleared(violation):
                if declared in BLOCKING_SEVERITIES:
                    return "Trivial"
            elif declared == "Critical":
                return "Major"
    if mode == "blocking" and declared not in BLOCKING_SEVERITIES:
        return "Major"
    return declared


def _violation_finding(*, mode: EnforcementMode, violation: dict[str, Any]) -> Finding:
    rule_id = str(violation.get("rule_id", "policy-violation"))
    path = str(violation.get("path", "."))
    message = str(violation.get("message", "policy violation"))
    declared = str(violation.get("severity", "Major"))
    severity = _gate_facing_severity(mode=mode, declared=declared, violation=violation)
    evidence: list[str] | None = None
    if severity != declared:
        evidence = [f"declared severity {declared} under {mode} enforcement"]
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
        evidence=evidence,
    )


def _contributes_blocker(*, mode: EnforcementMode, violation: dict[str, Any]) -> bool:
    """Return whether this violation blocks, read off the one gate-facing authority.

    Derived from the gate-facing severity rather than computed alongside it, so
    the flag and ``decide_approval`` cannot disagree (#554).
    """
    declared = str(violation.get("severity", "Major"))
    severity = _gate_facing_severity(mode=mode, declared=declared, violation=violation)
    return severity in BLOCKING_SEVERITIES


def evaluate_enforcement(
    mode: EnforcementMode,
    *,
    violation: dict[str, Any],
) -> EnforcementResult:
    """Map a policy violation to a gate-facing enforcement outcome (D7, D12, #554).

    Blocking intent lives in one place: the gate-facing severity. ``blocking``
    floors a non-blocking declared severity to ``Major`` so the rule blocks.
    ``required`` consults ``policy.evidence`` and blocks until declared evidence
    is present. ``warning`` and ``advisory`` never block — ``advisory`` caps
    blocking severities to ``Trivial`` and ``warning`` to ``Minor``. The
    declared severity is kept on the finding's ``evidence`` list whenever the
    gate-facing value differs.
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
