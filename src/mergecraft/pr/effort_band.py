"""Classifier-derived effort band — discrete sizing, not minute guesses (DG8)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

EffortBand = Literal["xs", "s", "m", "l", "xl"]


class EffortBandResult(BaseModel):
    """Discrete review-effort band derived from change signals."""

    model_config = ConfigDict(extra="forbid")

    band: EffortBand
    rationale: str


def _coerce_int(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) and value >= 0 else default


def classify_effort_band(
    *,
    diff: str,
    pr_metadata: dict[str, object],
    change_signals: dict[str, object],
) -> EffortBandResult:
    """Map change signals to a discrete effort band (never minute estimates)."""
    _ = diff
    _ = pr_metadata

    files_changed = _coerce_int(change_signals.get("files_changed"))
    lines_added = _coerce_int(change_signals.get("lines_added"))
    lines_deleted = _coerce_int(change_signals.get("lines_deleted"))
    total_lines = lines_added + lines_deleted

    if files_changed <= 1 and total_lines <= 10:
        band: EffortBand = "xs"
        rationale = (
            f"Single-file delta ({files_changed} file, +{lines_added}/-{lines_deleted} lines) "
            "fits the extra-small band."
        )
    elif files_changed <= 3 and total_lines <= 80:
        band = "s"
        rationale = f"Small multi-file change ({files_changed} files, +{lines_added}/-{lines_deleted} lines)."
    elif files_changed <= 10 and total_lines <= 400:
        band = "m"
        rationale = (
            f"Moderate breadth ({files_changed} files, +{lines_added}/-{lines_deleted} lines)."
        )
    elif files_changed <= 25 and total_lines <= 1500:
        band = "l"
        rationale = (
            f"Large change set ({files_changed} files, +{lines_added}/-{lines_deleted} lines)."
        )
    else:
        band = "xl"
        rationale = (
            f"Very large change set ({files_changed} files, +{lines_added}/-{lines_deleted} lines)."
        )

    return EffortBandResult(band=band, rationale=rationale)


__all__ = ["EffortBand", "EffortBandResult", "classify_effort_band"]
