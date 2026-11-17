"""Risk grade combining rules (#1489)."""

from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given

from mergecraft.classify.blast_radius import LaneReason, classify_blast_radius
from mergecraft.classify.risk import combine_risk_lanes


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
