"""Public tracing package surface.

Batch A (W2) ships the configuration schema, the canonical event model, the
local JSONL sink, and the redaction boundary. Remote exporters land in W8
behind the optional ``[tracing]`` extra (D6).
"""

from __future__ import annotations

from mergecraft.tracing.cap import TRACE_ATTRS_JSON_MAX_BYTES, cap_event_attrs
from mergecraft.tracing.content import (
    ContentCapture,
    capture_text,
    resolve_content_capture,
)
from mergecraft.tracing.event import TraceEvent
from mergecraft.tracing.exporters import (
    OTLPSink,
    resolve_token_ref,
)
from mergecraft.tracing.genai import (
    ModelParams,
    input_messages_attrs,
    output_messages_attrs,
    request_attrs,
    resolve_capture_policy,
    response_attrs,
    thinking_attrs,
    usage_attrs,
)
from mergecraft.tracing.redaction import DENY_KEYS, redact_attrs, redact_event
from mergecraft.tracing.review_context import (
    ReviewContext,
    bind_review_context,
    correlation_key_for,
    current_review_context,
    resolve_review_id,
    review_env_for_subprocess,
)
from mergecraft.tracing.sinks import (
    JSONLFileSink,
    MemorySink,
    MultiSink,
    NullSink,
    RedactingSink,
    read_jsonl_events,
    sink_factory,
)
from mergecraft.tracing.tracer import (
    _ACTIVE_SPAN,
    NullSpan,
    NullTracer,
    Span,
    Tracer,
    baseline_run_attrs,
    get_tracer_from_settings,
    resolve_correlation_from_env,
    resolve_session_id,
)


def current_tracer() -> Tracer | NullTracer | None:
    """Return the tracer that owns the currently-active mergeCraft ``Span``.

    Used by narrow instrumentation sites (``instrument_httpx`` consumers,
    custom provider wires) when the caller has not been handed a tracer
    explicitly but is known to be invoked under a traced span. Returns
    ``None`` when tracing is disabled or no span is active — the caller
    must treat that as a no-op rather than falling back to a fresh tracer
    (a fresh tracer would orphan the new span from the run's trace tree).
    """
    active = _ACTIVE_SPAN.get()
    if isinstance(active, Span):
        return active.tracer
    return None


__all__ = [
    "DENY_KEYS",
    "TRACE_ATTRS_JSON_MAX_BYTES",
    "ContentCapture",
    "JSONLFileSink",
    "MemorySink",
    "ModelParams",
    "MultiSink",
    "NullSink",
    "NullSpan",
    "NullTracer",
    "OTLPSink",
    "RedactingSink",
    "ReviewContext",
    "Span",
    "TraceEvent",
    "Tracer",
    "baseline_run_attrs",
    "bind_review_context",
    "cap_event_attrs",
    "capture_text",
    "correlation_key_for",
    "current_review_context",
    "current_tracer",
    "get_tracer_from_settings",
    "input_messages_attrs",
    "output_messages_attrs",
    "read_jsonl_events",
    "redact_attrs",
    "redact_event",
    "request_attrs",
    "resolve_capture_policy",
    "resolve_content_capture",
    "resolve_correlation_from_env",
    "resolve_review_id",
    "resolve_session_id",
    "resolve_token_ref",
    "response_attrs",
    "review_env_for_subprocess",
    "sink_factory",
    "thinking_attrs",
    "usage_attrs",
]
