"""PR risk grade: combine deterministic blast-radius with optional Jev raise-only overlay (#1489)."""

from __future__ import annotations

from typing import Final

from mergecraft.classify.blast_radius import (
    _AUTO_MERGE_LANE,
    _LANE_RANK,
    _NEXT_ACTION,
    BlastRadiusClassification,
    Lane,
    LaneReason,
)

_JEV_RECORD_CODES: Final[frozenset[str]] = frozenset({"jev.disabled", "jev.credential_absent"})


def lane_max(*lanes: Lane) -> Lane:
    """Return the highest lane by rank."""
    return max(lanes, key=lambda lane: _LANE_RANK[lane])


def combine_risk_lanes(
    deterministic: BlastRadiusClassification,
    jev_reasons: list[LaneReason] | None,
    *,
    jev_record: list[LaneReason] | None = None,
) -> BlastRadiusClassification:
    """Merge Jev overlay onto the deterministic floor; Jev may only raise the lane."""
    reasons = list(deterministic.reasons)
    det_lane = deterministic.lane
    if jev_record:
        reasons.extend(jev_record)
    raised: list[LaneReason] = []
    if jev_reasons:
        for reason in jev_reasons:
            if reason.code in _JEV_RECORD_CODES:
                reasons.append(reason)
                continue
            if _LANE_RANK[reason.lane] > _LANE_RANK[det_lane]:
                raised.append(reason)
                reasons.append(reason)
    lane = lane_max(det_lane, *(r.lane for r in raised)) if raised else det_lane
    categories = list(
        dict.fromkeys([*deterministic.categories, *(r.code.split(".")[0] for r in raised)])
    )
    primary = next(
        (r for r in reversed(reasons) if r.lane == lane), reasons[-1] if reasons else None
    )
    reason_text = primary.message if primary is not None else deterministic.reason
    return BlastRadiusClassification(
        lane=lane,
        auto_merge_lane=_AUTO_MERGE_LANE[lane],
        reason=reason_text,
        next_action=_NEXT_ACTION[lane],
        categories=categories,
        reasons=reasons,
        checklist=list(deterministic.checklist),
    )


def format_risk_line(classification: BlastRadiusClassification | None) -> str | None:
    """One-line ``Risk:`` summary for the review record."""
    if classification is None:
        return None
    lane = classification.lane
    codes = [
        str(reason.code)
        for reason in classification.reasons
        if str(reason.code) and not str(reason.code).startswith("baseline.")
    ]
    if not codes:
        codes = [str(reason.code) for reason in classification.reasons if str(reason.code)]
    code_tail = ", ".join(f"`{code}`" for code in codes) if codes else "`baseline.clean`"
    return f"**Risk:** `{lane}` — {code_tail}"


__all__ = ["combine_risk_lanes", "format_risk_line", "lane_max"]
