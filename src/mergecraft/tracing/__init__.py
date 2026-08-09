"""Public tracing package surface.

Batch A (W2) ships the configuration schema, the canonical event model, the
local JSONL sink, and the redaction boundary. Remote exporters land in W8
behind the optional ``[tracing]`` extra (D6).
"""

from __future__ import annotations

from mergecraft.tracing.cap import TRACE_ATTRS_JSON_MAX_BYTES, cap_event_attrs
from mergecraft.tracing.event import TraceEvent
from mergecraft.tracing.redaction import DENY_KEYS, redact_attrs, redact_event
from mergecraft.tracing.sinks import (
    JSONLFileSink,
    MemorySink,
    MultiSink,
    NullSink,
    RedactingSink,
    read_jsonl_events,
    sink_factory,
)

__all__ = [
    "DENY_KEYS",
    "TRACE_ATTRS_JSON_MAX_BYTES",
    "JSONLFileSink",
    "MemorySink",
    "MultiSink",
    "NullSink",
    "RedactingSink",
    "TraceEvent",
    "cap_event_attrs",
    "read_jsonl_events",
    "redact_attrs",
    "redact_event",
    "sink_factory",
]
