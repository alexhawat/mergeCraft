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
        return EvidenceOutcome(
            status="inconclusive",
            reason=f"required evidence unavailable: {joined}",
            run_outcome=RunOutcome.inconclusive,
        )
    return EvidenceOutcome(
        status="satisfied",
        reason="all required evidence present",
        run_outcome=RunOutcome.passed,
    )


__all__ = [
    "EvidenceOutcome",
    "evaluate_rule_evidence",
]
