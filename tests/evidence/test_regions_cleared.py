"""D8 cheap pin — optional ``regions_cleared`` on ``TrajectoryRecord`` round-trips."""

from __future__ import annotations

from mergecraft.evidence.trajectory import TrajectoryRecord


def test_regions_cleared_round_trips_through_trajectory_record() -> None:
    """W11.1 / D8 — diff regions ruled out serialize and deserialize."""
    regions = ["src/app.py:10-24", "tests/app_test.py:40-55"]
    record = TrajectoryRecord(
        sources=["mcp-tool-calls"],
        read_coverage=True,
        regions_cleared=regions,
    )
    payload = record.model_dump(mode="json")
    assert payload["regions_cleared"] == regions

    restored = TrajectoryRecord.model_validate(payload)
    assert restored.regions_cleared == regions
    assert restored.read_coverage is True
