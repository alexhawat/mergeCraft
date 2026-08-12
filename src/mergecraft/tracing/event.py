"""Canonical trace event model (W2.2).

A :class:`TraceEvent` is one typed span — ``mergecraft.run``, ``agent.attempt``,
``llm.call``, ``tool.call``, ``mergecraft.analyzers.pipeline``, and so on.
The shape mirrors the W1.3 contract: required fields are typed, ``attrs`` is
free-form, ``parent_span_id`` may be null for root spans.

Every span emitted by a single ``mergecraft diff-review`` run shares one
``trace_id`` — the Logfire / OpenTelemetry trace identifier that groups every
span in one run under a single trace. ``session_id`` remains the per-process
correlation id (the W4 batch-B session correlation) and ``turn_id`` is the
per-span uuid4. The ``extra="ignore"`` config keeps the JSONL file sink
forward-compatible: events written without ``trace_id`` still round-trip
cleanly and the field is skipped on emit.

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

    Fields:
        kind: Canonical span kind (``mergecraft.run`` / ``agent.attempt`` / etc.).
        span_id: Unique per-span uuid4 hex (the leaf identifier).
        parent_span_id: Parent spans ``span_id``, or ``None`` for the root.
        session_id: Per-process correlation id (``resolve_session_id``).
        trace_id: The Logfire / OTel trace identifier shared by every span
            in one run (``resolve_trace_id``). Same value on every
            :class:`TraceEvent` in a single process for a single run.
        turn_id: Per-span uuid4 (``uuid4().hex``). One per span.
        tier: Trust tier (``trusted`` / ``balanced`` / ``untrusted``).
        ts_start_ns / ts_end_ns: Wall-clock nanoseconds.
        status: ``ok`` / ``error`` / similar.
        attrs: Free-form attribute dict.
    """

    model_config = ConfigDict(extra="ignore")

    kind: str
    span_id: str
    parent_span_id: str | None = None
    session_id: str
    trace_id: str = ""
    turn_id: str
    tier: str
    ts_start_ns: int
    ts_end_ns: int
    status: str
    attrs: dict[str, Any] = Field(default_factory=dict)


__all__ = ["TraceEvent"]
