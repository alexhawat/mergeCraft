"""OpenTelemetry context helpers for mergeCraft trace/span identity.

Parses mergeCraft hex ``trace_id`` / ``span_id`` values into OTel
``SpanContext`` fields, builds parent contexts for ``start_span``, isolates
root spans from leaked process context, and rewrites span ids after export.

The OTel SDK is an optional dependency (the ``[tracing]`` extra, D6). Every
entry point returns ``None`` when ``opentelemetry`` is not installed so
callers can degrade without raising.

Exports:
    parse_mergecraft_otel_trace_id — 128-bit OTel trace id from mergeCraft hex.
    parse_mergecraft_otel_span_id — 64-bit OTel span id from mergeCraft hex.
    build_otel_parent_context — OTel ``context`` for a parent ``SpanContext``.
    root_otel_context — OTel ``context`` with no parent (root isolation).
    override_span_context — rewrite ``trace_id`` / ``span_id`` on a span.
    resolve_start_context — parent or root context for ``start_span`` / attach.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

__all__ = [
    "build_otel_parent_context",
    "override_span_context",
    "parse_mergecraft_otel_span_id",
    "parse_mergecraft_otel_trace_id",
    "resolve_start_context",
    "root_otel_context",
]


def parse_mergecraft_otel_trace_id(trace_id: str) -> int | None:
    """Parse a mergeCraft ``trace_id`` hex string into a 128-bit OTel trace id."""
    try:
        return int(trace_id[:32], 16)
    except (TypeError, ValueError):  # fmt: skip
        return None


def parse_mergecraft_otel_span_id(span_id: str) -> int | None:
    """Parse a mergeCraft ``span_id`` hex string into a 64-bit OTel span id."""
    try:
        return int(span_id[:16], 16)
    except (TypeError, ValueError):  # fmt: skip
        return None


def build_otel_parent_context(trace_id: int, parent_span_id: str | None) -> Any | None:
    """Return an OTel ``context`` carrying the parent ``SpanContext``, if any."""
    if not parent_span_id:
        return None
    parent_otel_span_id = parse_mergecraft_otel_span_id(parent_span_id)
    if parent_otel_span_id is None:
        return None
    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, TraceState
    except ImportError:
        return None
    parent_ctx = SpanContext(
        trace_id=trace_id,
        span_id=parent_otel_span_id,
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
        trace_state=TraceState(),
    )
    return otel_trace.set_span_in_context(NonRecordingSpan(parent_ctx))


def root_otel_context() -> Any | None:
    """Return an OTel ``context`` with no parent span (isolates from leaked context)."""
    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.trace import INVALID_SPAN_CONTEXT, NonRecordingSpan
    except ImportError:
        return None
    return otel_trace.set_span_in_context(NonRecordingSpan(INVALID_SPAN_CONTEXT))


def override_span_context(span: Any, trace_id: int, span_id: int) -> None:
    """Rewrite the OTel ``trace_id`` and ``span_id`` on a freshly-built span."""
    try:
        from opentelemetry.trace import SpanContext, TraceFlags, TraceState
    except ImportError:
        return
    try:
        new_ctx = SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            is_remote=False,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
            trace_state=TraceState(),
        )
        if hasattr(span, "_context"):
            span._context = new_ctx
    except Exception as exc:
        logger.debug("trace otel span context override failed: {}", exc)


def resolve_start_context(trace_id: str, parent_span_id: str | None) -> Any | None:
    """Return the OTel ``context`` for ``start_span`` / ``attach_trace_context``.

    Root spans (no ``parent_span_id``) and malformed non-empty ``parent_span_id``
    values fail closed to :func:`root_otel_context` so leaked process context
    never becomes an implicit parent. Valid parents use
    :func:`build_otel_parent_context`. Returns ``None`` when ``trace_id`` cannot
    be parsed or OTel is not installed.
    """
    otel_trace_id = parse_mergecraft_otel_trace_id(trace_id)
    if otel_trace_id is None:
        return None
    if not parent_span_id:
        return root_otel_context()
    parent_context = build_otel_parent_context(otel_trace_id, parent_span_id)
    if parent_context is None:
        return root_otel_context()
    return parent_context
