"""Policy evidence requirements — missing evidence yields inconclusive (D8)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mergecraft.run_outcome import RunOutcome


@dataclass(frozen=True, slots=True)
class EvidenceOutcome:
    """Result of checking required evidence for one rule."""

    status: str
    reason: str
    run_outcome: RunOutcome | None = None


def _required_evidence_keys(rule: dict[str, Any]) -> list[str]:
    evidence = rule.get("evidence")
    if not isinstance(evidence, dict):
        return []
    required = evidence.get("required")
    if not isinstance(required, list):
        return []
    return [str(item) for item in required]


REQUIREMENTS_EVIDENCE_KEY = "requirements"


def requirements_evidence_required(rule: dict[str, Any]) -> bool:
    """Return whether policy requires requirements evidence before a review can pass.

    Missing requirements evidence still flows through ``evaluate_rule_evidence``
    as ``inconclusive`` — ``decide_approval()`` remains the only approval gate
    (D14 / #352).
    """
    return REQUIREMENTS_EVIDENCE_KEY in _required_evidence_keys(rule)


def evaluate_rule_evidence(
    rule: dict[str, Any],
    *,
    available_evidence: dict[str, object],
) -> EvidenceOutcome:
    """Return ``inconclusive`` when any required evidence key is unavailable (D8)."""
    required = _required_evidence_keys(rule)
    missing = [key for key in required if key not in available_evidence]
    if missing:
        joined = ", ".join(missing)
        reason = f"required evidence unavailable: {joined}"
        if requirements_evidence_required(rule) and REQUIREMENTS_EVIDENCE_KEY in missing:
            reason = f"{reason} (requirements evidence required)"
        return EvidenceOutcome(
            status="inconclusive",
            reason=reason,
            run_outcome=RunOutcome.inconclusive,
        )
    return EvidenceOutcome(
        status="satisfied",
        reason="all required evidence present",
        run_outcome=RunOutcome.passed,
    )


__all__ = [
    "REQUIREMENTS_EVIDENCE_KEY",
    "EvidenceOutcome",
    "evaluate_rule_evidence",
    "requirements_evidence_required",
]
