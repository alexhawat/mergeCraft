"""Declarative routing triggers for registry lens entries (AP4/AP5)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

RiskBand = Literal["low", "medium", "high"]


class LensTriggers(BaseModel):
    """Resolved trigger metadata for risk-based lens routing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    categories: tuple[str, ...] = ()
    min_risk_band: RiskBand | None = None
