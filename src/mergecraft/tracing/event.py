"""Canonical trace event model (W2.2).

A :class:`TraceEvent` is one typed span — ``mergecraft.run``, ``agent.attempt``,
``llm.call``, ``tool.call``, ``mergecraft.analyzers.pipeline``, and so on.
The shape mirrors the W1.3 contract: required fields are typed, ``attrs`` is
free-form, ``parent_span_id`` may be null for root spans.

Exports:
    TraceEvent -- Pydantic model for one span.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TraceEvent(BaseModel):
    """One typed span recorded by an emit site.

    ``model_dump()`` (no ``by_alias``) returns the snake_case dict that matches
    the YAML / JSON shape used by ``tests/tracing/conftest.py`` —
    ``event.model_dump() == trace_event_data``.
    """

    model_config = ConfigDict(extra="ignore")

    kind: str
    span_id: str
    parent_span_id: str | None = None
    session_id: str
    turn_id: str
    tier: str
    ts_start_ns: int
    ts_end_ns: int
    status: str
    attrs: dict[str, Any] = Field(default_factory=dict)


__all__ = ["TraceEvent"]
