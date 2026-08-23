"""Collateral naming prompt contract (RC11) — W8.1 RED suite.

Wave plan: ``.ignorelocal/waves/review-convergence-wave-plan.md`` (W8).
Pins the collateral clause in Review step 6 and IncrementalReview step 8.
Implementation lands in W8.2b.
"""

from __future__ import annotations

import re

from mergecraft.modes import IncrementalReview, Review

_REVIEW_AGGREGATE_STEP = 6
_INCREMENTAL_AGGREGATE_STEP = 8


def _aggregate_step(template: str, step_num: int) -> str:
    marker = f"{step_num}. **aggregate"
    start = template.index(marker)
    next_marker = f"{step_num + 1}. "
    end = template.find(next_marker, start + 1)
    return template[start : end if end != -1 else len(template)]


def _review_aggregate_step() -> str:
    return _aggregate_step(Review.TEMPLATE, _REVIEW_AGGREGATE_STEP)


def _incremental_aggregate_step() -> str:
    return _aggregate_step(IncrementalReview.TEMPLATE, _INCREMENTAL_AGGREGATE_STEP)


def _both_aggregate_steps() -> tuple[str, str]:
    return _review_aggregate_step(), _incremental_aggregate_step()


def test_major_findings_are_asked_to_name_collateral() -> None:
    """RC11 — Major+ findings must name collateral paths in the aggregate step."""
    review_step, incremental_step = _both_aggregate_steps()

    for label, step in (
        ("Review", review_step),
        ("IncrementalReview", incremental_step),
    ):
        lowered = step.lower()
        assert "collateral" in lowered, f"{label} aggregate step never names collateral"
        assert "major" in lowered, f"{label} aggregate step does not scope collateral to Major"
        assert "critical" in lowered, (
            f"{label} aggregate step does not include Critical in the collateral scope"
        )


def test_collateral_is_not_required_for_minor_or_trivial() -> None:
    """RC11 — do not inflate Minor/Trivial findings with collateral essays."""
    review_step, incremental_step = _both_aggregate_steps()

    for label, step in (
        ("Review", review_step),
        ("IncrementalReview", incremental_step),
    ):
        lowered = step.lower()
        assert "collateral" in lowered, f"{label} aggregate step has no collateral clause"
        assert "minor" in lowered, f"{label} aggregate step does not name Minor exemptions"
        assert "trivial" in lowered, f"{label} aggregate step does not name Trivial exemptions"
        assert re.search(
            r"not required|do not require|skip collateral|never require|omit collateral",
            lowered,
        ), f"{label} aggregate step does not exempt Minor/Trivial from collateral"


def test_collateral_claims_are_subject_to_the_evidence_rule() -> None:
    """REVIEW-CHECKS §6 — unevidenced collateral outside the diff is a question or drop."""
    review_step, incremental_step = _both_aggregate_steps()
    combined = review_step + incremental_step
    lowered = combined.lower()

    assert "collateral" in lowered, "aggregate steps never mention collateral"
    assert re.search(
        r"question or (a )?drop|downgraded to a question|downgrade.*question",
        lowered,
    ), "collateral clause does not bind unevidenced claims to question-or-drop"
    assert re.search(
        r"evidence|speculative|unverified|diff doesn't contain|diff does not contain",
        lowered,
    ), "collateral clause does not cite the §6 evidence rule"
