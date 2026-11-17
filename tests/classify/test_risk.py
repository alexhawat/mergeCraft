"""Risk grade combining rules (#1489)."""

from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given

from mergecraft.classify.blast_radius import (
    BlastRadiusClassification,
    LaneReason,
    classify_blast_radius,
)
from mergecraft.classify.risk import combine_risk_lanes, format_risk_line


def test_combine_never_lowers_deterministic_lane() -> None:
    det = classify_blast_radius({"changed_paths": ["src/a.py"], "diff_stats": {"files_changed": 1}})
    det = det.model_copy(update={"lane": "medium"})
    jev = [
        LaneReason(code="jev.data_loss", lane="low", message="jev said low"),
    ]
    combined = combine_risk_lanes(det, jev)
    assert combined.lane == det.lane


@given(
    det_lane=st.sampled_from(["low", "medium", "high"]),
    jev_lane=st.sampled_from(["low", "medium", "high"]),
)
def test_combine_property_jev_only_raises(det_lane: str, jev_lane: str) -> None:
    det = classify_blast_radius(
        {
            "changed_paths": ["src/a.py"],
            "diff_stats": {"files_changed": 1, "lines_changed": 3},
        }
    )
    det = det.model_copy(update={"lane": det_lane})
    jev = [LaneReason(code="jev.authz", lane=jev_lane, message="test")]
    combined = combine_risk_lanes(det, jev)
    ranks = {"low": 0, "medium": 1, "high": 2}
    assert ranks[combined.lane] >= ranks[det_lane]


def test_format_risk_line_omits_baseline_codes() -> None:
    classification = BlastRadiusClassification(
        lane="medium",
        auto_merge_lane="assisted",
        reason="test",
        next_action="review",
        categories=["source"],
        reasons=[
            LaneReason(code="baseline.clean", lane="low", message="clean"),
            LaneReason(code="source.changed", lane="medium", message="src"),
        ],
        checklist=[],
    )
    line = format_risk_line(classification)
    assert line is not None
    assert "`source.changed`" in line
    assert "baseline" not in line


def test_format_risk_line_none_when_no_classification() -> None:
    assert format_risk_line(None) is None
