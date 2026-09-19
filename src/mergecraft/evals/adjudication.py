"""Provenance tiers and the calibration bar for eval corpus labels (#736).

Scores are reported for any corpus; what they *entitle a caller to claim* is a
separate question, answered here. A label's ``provenance`` maps to an
independence tier, and a set of labels backs a calibration claim only when every
one of them meets the configured bar.

The corpus this guards is agent-seeded. Scoring a judge against labels the same
model produced is circular, so those labels sit at the lowest tier and cannot
support a comparative claim no matter how a repository is configured.

Module: mergecraft.evals.adjudication
Depends: typing, pydantic, loguru

Exports:
    IndependenceTier: How independent a label is of the system under test.
    tier_for_provenance: Map a stored ``provenance`` string to its tier.
    CalibrationStatus: Whether a label set may back a calibration claim.
    calibration_status: Partition labels by tier and decide eligibility.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Iterable

IndependenceTier = Literal["independent", "model", "none"]

#: Ordering used to compare a label's tier against the configured bar.
_TIER_RANK: dict[IndependenceTier, int] = {"none": 0, "model": 1, "independent": 2}

#: Tier of each ``provenance`` string the corpus can carry. Adjudicated values
#: are recognised here so a label written by a future adjudicator is scored
#: correctly, even though nothing in this module writes one.
_TIER_BY_PROVENANCE: dict[str, IndependenceTier] = {
    "human": "independent",
    "jev-adjudicated": "model",
    "llm-adjudicated": "model",
    "agent-seeded": "none",
    "": "none",
}


def tier_for_provenance(provenance: str) -> IndependenceTier:
    """Map a stored ``provenance`` string to its independence tier.

    Unknown strings resolve to ``none`` so an unrecognised label can never
    silently satisfy a calibration bar.
    """
    return _TIER_BY_PROVENANCE.get(provenance.strip(), "none")


class CalibrationStatus(BaseModel):
    """Whether a set of labels may back a calibration claim."""

    model_config = ConfigDict(extra="forbid")

    counts: dict[str, int] = Field(default_factory=dict)
    required: IndependenceTier = "independent"
    eligible: bool = False
    reason: str = ""


def calibration_status(
    provenances: Iterable[str],
    *,
    required: IndependenceTier = "independent",
) -> CalibrationStatus:
    """Partition labels by tier and decide whether they meet ``required``.

    A label set is eligible only when it is non-empty and **every** label
    meets the bar. One agent-seeded row is enough to make a corpus-wide
    calibration claim indefensible, so this deliberately does not take a
    majority or a ratio.

    Args:
        provenances: The ``provenance`` string of each label considered.
        required: Minimum tier every label must meet.

    Returns:
        CalibrationStatus: Per-tier counts, eligibility, and a stated reason.
    """
    counts: dict[IndependenceTier, int] = {"independent": 0, "model": 0, "none": 0}
    for provenance in provenances:
        counts[tier_for_provenance(provenance)] += 1
    total = sum(counts.values())
    if required == "none":
        # Refused even though the type admits it: every provenance clears a
        # zero bar, so honouring it would publish unadjudicated labels as
        # calibrated. Configuration cannot reach here, and a programmatic
        # caller does not get a different answer than an operator would.
        return CalibrationStatus(
            counts={str(tier): count for tier, count in counts.items()},
            required=required,
            eligible=False,
            reason="'none' is not a calibration bar — no label independence is required",
        )
    bar = _TIER_RANK[required]
    below = sum(count for tier, count in counts.items() if _TIER_RANK[tier] < bar)
    if total == 0:
        reason = "no labels to score"
    elif below:
        reason = f"{below} of {total} labels below the {required!r} bar"
    else:
        reason = f"all {total} labels meet the {required!r} bar"
    eligible = total > 0 and below == 0
    if not eligible:
        logger.debug("calibration claim withheld — {}", reason)
    return CalibrationStatus(
        counts={str(tier): count for tier, count in counts.items()},
        required=required,
        eligible=eligible,
        reason=reason,
    )


__all__ = [
    "CalibrationStatus",
    "IndependenceTier",
    "calibration_status",
    "tier_for_provenance",
]
