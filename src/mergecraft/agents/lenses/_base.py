"""Lens definition primitives (AP5)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from mergecraft.agents.lens_triggers import LensTriggers  # noqa: TC001 — Pydantic field type
from mergecraft.mcp.shared import ToolClass  # noqa: TC001 — Pydantic field type


class LensDefinition(BaseModel):
    """Bundled themed lens metadata rendered into registry bindings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lens_id: str
    title: str
    rubric: str
    triggers: LensTriggers
    required_evidence: tuple[str, ...]
    tool_classes: frozenset[ToolClass]
