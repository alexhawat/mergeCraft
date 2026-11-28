"""Typed merge-attention grade carried on the evidence packet (#1609)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AttentionLevel = Literal["low", "medium", "high"]
AttentionAxis = Literal[
    "alignment",
    "impact",
    "verification",
    "rollback_cost",
    "error_detection",
]
VerdictSource = Literal["deterministic", "model"]

AXIS_ORDER: tuple[AttentionAxis, ...] = (
    "alignment",
    "impact",
    "verification",
    "rollback_cost",
    "error_detection",
)


class AxisVerdict(BaseModel):
    """One axis: categorical level, one-line verdict, and how it was sourced."""

    model_config = ConfigDict(extra="forbid")

    axis: AttentionAxis
    level: AttentionLevel
    verdict: str = Field(min_length=1, max_length=280)
    source: VerdictSource = "deterministic"
    verification_gaps: list[str] = Field(default_factory=list)


class MergeAttentionSection(BaseModel):
    """Human-attention grade for one run; never consumed by merge gates."""

    model_config = ConfigDict(extra="forbid")

    overall: AttentionLevel
    axes: list[AxisVerdict] = Field(min_length=5, max_length=5)
    uncalibrated: bool = True
    rubric_doc: str = "docs/merge-attention.md"


__all__ = [
    "AXIS_ORDER",
    "AttentionAxis",
    "AttentionLevel",
    "AxisVerdict",
    "MergeAttentionSection",
    "VerdictSource",
]
