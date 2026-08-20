"""OTel context bridge — propagate the mergeCraft trace_id to OTel spans.

When the mergeCraft :class:`mergecraft.tracing.tracer.Tracer` emits a span,
this module sets the **real** OpenTelemetry ``trace_id`` on the produced
OTel span so Logfire (and any other OTel backend) groups every span in one
mergeCraft run under a single trace. The :func:`attach_trace_context`
context manager is the bridge point for any nested OTel auto-instrumented
operation (e.g. an ``httpx`` call inside a tool) so it inherits the same
``trace_id`` without the caller having to know about mergeCraft's tracer.

The OTel SDK is an optional dependency (the ``[tracing]`` extra, D6). When
it is uninstalled, :func:`attach_trace_context` returns a no-op context
manager so callers can use the API unconditionally without first checking
the module's presence.

Exports:
    attach_trace_context — context manager that sets the OTel ``trace_id``
        from a mergeCraft :class:`mergecraft.tracing.tracer.Span` onto the
        current OTel context for the duration of the ``with`` block.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from mergecraft.tracing.tracer import Span


@contextlib.contextmanager
def attach_trace_context(span: Span) -> Iterator[None]:
    """Attach an OTel span whose ``trace_id`` matches ``span.trace_id``.

    Within the ``with`` block, ``opentelemetry.trace.get_current_span()``
    returns a span whose :class:`opentelemetry.trace.SpanContext` carries
    the mergeCraft run's ``trace_id`` (parsed as a 128-bit unsigned int).
    Any nested OTel auto-instrumented call (``httpx``, ``requests``, …)
    therefore inherits the same trace without the caller knowing about
    mergeCraft's :class:`mergecraft.tracing.tracer.Tracer`.

    The bridge is defensive: when the ``[tracing]`` extra is not installed
    the function yields once and returns so callers can use the API
    unconditionally.

    Args:
        span (Span): The mergeCraft span whose ``trace_id`` should be
            propagated onto the OTel context.

    Yields:
        None: The yield point is the inner block of the ``with`` statement.

    Examples:
        >>> from mergecraft.tracing import Tracer
        >>> tracer = Tracer(sink=object(), session_id="s", run_id="r")
        >>> with tracer.start_span("mergecraft.run") as span, attach_trace_context(span):
        ...     pass
    """
    try:
        from opentelemetry import context as otel_context
        from opentelemetry import trace as otel_trace
        from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, TraceState
    except ImportError:
        # ``[tracing]`` extra is not installed — the bridge is a no-op.
        yield
        return

    try:
        otel_trace_id = int(span.trace_id[:32], 16) if span.trace_id else None
    except (TypeError, ValueError):  # fmt: skip
        # Malformed trace_id (e.g. not hex) — degrade to a no-op rather
        # than fail the caller's review (convention 6).
        yield
        return

    if not otel_trace_id:
        yield
        return

    # The OTel global tracer provider may be the ProxyTracerProvider when
    # no real exporter has been configured. We still need a real SDK span
    # so ``end()`` is meaningful; falling back to the proxy's tracer
    # returns a ``NonRecordingSpan`` whose context we can still wrap.
    provider = otel_trace.get_tracer_provider()
    tracer = provider.get_tracer("mergecraft.tracing.otel_bridge")

    otel_span = tracer.start_span(
        span.kind,
        attributes={
            "mergecraft.span_id": span.span_id,
            "mergecraft.trace_id": span.trace_id,
            "mergecraft.session_id": span.session_id,
        },
    )

    span_ctx = otel_span.get_span_context()
    bridged_ctx = SpanContext(
        trace_id=otel_trace_id,
        span_id=span_ctx.span_id,
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
        trace_state=TraceState(),
    )
    bridged_span = NonRecordingSpan(bridged_ctx)
    bridged_otel_ctx = otel_trace.set_span_in_context(bridged_span)
    token = otel_context.attach(bridged_otel_ctx)
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            # Defensive: a stale token is harmless, never fail the caller.
            otel_context.detach(token)
        with contextlib.suppress(Exception):
            otel_span.end()


__all__ = ["attach_trace_context"]
