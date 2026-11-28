"""Internal lane combination for merge-attention (uncalibrated heuristic)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mergecraft.merge_attention.types import AttentionLevel

_LEVEL_RANK: dict[AttentionLevel, int] = {"low": 0, "medium": 1, "high": 2}


def max_level(*levels: AttentionLevel | str) -> AttentionLevel:
    """Return the highest attention level."""
    normalized: list[AttentionLevel] = [
        level for level in levels if level in ("low", "medium", "high")
    ]
    if not normalized:
        return "medium"
    return max(normalized, key=lambda level: _LEVEL_RANK[level])


def lane_to_attention(lane: str | None) -> AttentionLevel:
    """Map blast-radius lane strings to attention impact levels."""
    normalized = (lane or "").strip().lower()
    if normalized == "high":
        return "high"
    if normalized == "low":
        return "low"
    return "medium"


__all__ = ["lane_to_attention", "max_level"]
