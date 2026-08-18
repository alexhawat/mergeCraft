"""DG5 policy evidence requirements — missing evidence is inconclusive (D8).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG5).
Implementation: **DG5.2** — required evidence with fail-closed evaluation.
"""

from __future__ import annotations

from mergecraft.run_outcome import RunOutcome


def test_missing_required_evidence_yields_inconclusive() -> None:
    """A rule whose required evidence is unavailable never silently passes."""
    from mergecraft.policy.evidence import evaluate_rule_evidence

    rule = {
        "id": "coverage-floor",
        "evidence": {"required": ["static-check:coverage"]},
    }
    available_evidence: dict[str, object] = {}

    outcome = evaluate_rule_evidence(rule, available_evidence=available_evidence)

    assert outcome.status == "inconclusive"
    assert outcome.run_outcome == RunOutcome.inconclusive
    assert "coverage" in outcome.reason.lower()
