"""Shared JSONL trace loading for ``replay`` / ``run inspect`` / ``run diff``."""

from __future__ import annotations

from mergecraft.tracing.trace_jsonl import (
    default_trace_dir,
    load_trace_jsonl_events,
    session_ids_in_trace_order,
)

__all__ = ["default_trace_dir", "load_trace_jsonl_events", "session_ids_in_trace_order"]
