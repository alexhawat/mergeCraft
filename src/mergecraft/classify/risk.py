"""PR risk grade: combine deterministic blast-radius with optional Jev raise-only overlay (#1489)."""

from __future__ import annotations

from mergecraft.classify.blast_radius import (
    _AUTO_MERGE_LANE,
    _NEXT_ACTION,
    BlastRadiusClassification,
    Lane,
    LaneReason,
    lane_rank,
)


def lane_max(*lanes: Lane) -> Lane:
    """Return the highest lane by rank."""
    return max(lanes, key=lane_rank)


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
    raised = [
        reason for reason in jev_reasons or [] if lane_rank(reason.lane) > lane_rank(det_lane)
    ]
    if not raised:
        return (
            deterministic.model_copy(update={"reasons": reasons}) if jev_record else deterministic
        )
    reasons.extend(raised)
    lane = det_lane
    for reason in raised:
        lane = lane_max(lane, reason.lane)
    categories = list(
        dict.fromkeys([*deterministic.categories, *(r.code.split(".")[0] for r in raised)])
    )
    primary = next(reason for reason in reversed(raised) if reason.lane == lane)
    return BlastRadiusClassification(
        lane=lane,
        auto_merge_lane=_AUTO_MERGE_LANE[lane],
        reason=primary.message,
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
        reason.code
        for reason in classification.reasons
        if reason.code and not reason.code.startswith("baseline.")
    ]
    if not codes:
        return f"**Risk:** `{lane}`"
    code_tail = ", ".join(f"`{code}`" for code in codes)
    return f"**Risk:** `{lane}` — {code_tail}"


def jev_skip_reasons(code: str) -> list[LaneReason]:
    """Record why Jev did not return a grade, without affecting the lane."""
    return [
        LaneReason(
            code=f"jev.{code.replace('_', '.')}",
            lane="low",
            message=f"Jev risk grade unavailable ({code})",
        )
    ]


__all__ = ["combine_risk_lanes", "format_risk_line", "jev_skip_reasons", "lane_max"]
