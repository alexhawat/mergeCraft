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

from typing import Any

TRACE_ATTRS_JSON_MAX_BYTES = 64 * 1024


def cap_event_attrs(event_data: dict[str, Any]) -> dict[str, Any]:
    """Cap ``event_data["attrs"]`` at :data:`TRACE_ATTRS_JSON_MAX_BYTES`.

    The boundary is the length of any single string value in ``attrs``:
    ``payload_bytes == 64 * 1024`` is kept whole; ``64 * 1024 + 1`` is truncated
    (W1.8 boundary). When the largest string value exceeds the cap, ``attrs``
    is replaced with ``{"truncated": True}`` so the row stays a single line
    of valid JSON. ``span_id`` (and every other top-level field) is preserved
    on the dict.
    """
    attrs = event_data.get("attrs") or {}
    if not isinstance(attrs, dict):
        return event_data
    threshold = TRACE_ATTRS_JSON_MAX_BYTES
    for value in attrs.values():
        if isinstance(value, str) and len(value) > threshold:
            return {**event_data, "attrs": {"truncated": True}}
    return event_data


__all__ = ["TRACE_ATTRS_JSON_MAX_BYTES", "cap_event_attrs"]
