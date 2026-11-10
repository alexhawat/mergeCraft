"""Bounded payload size for ``TraceEvent.attrs`` (D8).

A 64 KiB JSON-encoded ``attrs`` blob is the per-event ceiling for local sinks.
Above the cap, the original ``attrs`` is replaced with ``{"truncated": True}``
so the row still survives on disk and the run still produces a parseable
trace; downstream consumers see the marker rather than a missing or
half-written record.

Exports:
    TRACE_ATTRS_JSON_MAX_BYTES -- the cap in bytes (64 KiB).
    cap_event_attrs -- mutate-and-return; caps ``attrs`` and preserves span_id.
"""

from __future__ import annotations

import json
from typing import Any

TRACE_ATTRS_JSON_MAX_BYTES = 64 * 1024


def attrs_json_bytes(attrs: dict[str, Any]) -> int:
    """UTF-8 byte length of ``attrs`` as JSON written by the JSONL sink."""
    return len(json.dumps(attrs).encode("utf-8"))


def cap_event_attrs(event_data: dict[str, Any]) -> dict[str, Any]:
    """Cap ``event_data["attrs"]`` at :data:`TRACE_ATTRS_JSON_MAX_BYTES`.

    The boundary is the UTF-8 byte length of the whole ``attrs`` dict encoded
    as JSON (nested values and many individually small values count):
    exactly ``64 * 1024`` bytes is kept whole; ``64 * 1024 + 1`` is truncated
    (W1.8 boundary). Over the cap, ``attrs`` is replaced with
    ``{"truncated": True}`` so the row stays a single line of valid JSON.
    Attrs that cannot be JSON-encoded at all are truncated the same way.
    ``span_id`` (and every other top-level field) is preserved on the dict.
    """
    attrs = event_data.get("attrs") or {}
    if not isinstance(attrs, dict):
        return event_data
    try:
        size = attrs_json_bytes(attrs)
    except (TypeError, ValueError, RecursionError):
        return {**event_data, "attrs": {"truncated": True}}
    if size > TRACE_ATTRS_JSON_MAX_BYTES:
        return {**event_data, "attrs": {"truncated": True}}
    return event_data


__all__ = ["TRACE_ATTRS_JSON_MAX_BYTES", "cap_event_attrs"]
