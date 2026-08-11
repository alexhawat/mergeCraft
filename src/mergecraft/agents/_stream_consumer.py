"""Shared NDJSON stream consumer for agent driver migrations (W6).

Module: mergecraft.agents._stream_consumer
Depends: mergecraft.agents.shared, mergecraft.tracing.event, loguru

The W6 migration replaces ``subprocess.run(..., capture_output=True)`` with
incremental reads in the agent drivers that can stream. The driver's stdout is
a sequence of NDJSON events (Claude ``stream-json``, ``codex exec --json``,
``gemini --output-format stream-json``); each event becomes either a
``tool.call`` or ``llm.call`` span emitted through the standard tracer
pathway, so the existing ``MemorySink`` / ``JSONLFileSink`` surface sees it.

The consumer is intentionally **driver-agnostic**: it knows how to read lines
from a stream, parse them as JSON, skip malformed lines (W6.5), echo lines
to stdout so the activity monitor stays armed (D13), and surface a classifier
callback for driver-specific span emission.

Exports:
    StreamSpanAccumulator -- per-run aggregator for usage + final output.
    consume_stream -- iterate a line stream and dispatch events to a classifier.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mergecraft.agents.shared import AgentUsage
    from mergecraft.tracing.tracer import Span

# A classifier decides for each parsed event whether to emit a tool.call span,
# an llm.call span, or drop the event entirely. The callable receives the
# parsed dict and the StreamSpanAccumulator; the driver-level code resolves
# the tracer and parent span id and calls ``_emit_event_span`` (defined in
# this module) when a span should be opened and closed.
EventHandler = Callable[["StreamSpanAccumulator", dict[str, Any]], None]


@dataclass(slots=True)
class StreamSpanAccumulator:
    """Per-run aggregator: folds partial usage events into a final ``AgentUsage``.

    Claude ``stream-json`` and ``codex exec --json`` emit usage on
    ``message_start`` and ``message_delta`` events, not as a single terminal
    record. The accumulator buffers them so the final ``AgentUsage`` matches
    what the legacy blob parser would have surfaced.
    """

    agent_name: str
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost_usd: float | None = None
    final_output: str | None = None
    parsed_event_count: int = 0
    malformed_event_count: int = 0

    def absorb_usage(self, usage_payload: Mapping[str, Any] | None) -> None:
        """Fold one event's ``usage`` mapping into the accumulator totals."""
        if not isinstance(usage_payload, dict):
            return
        self.tokens_in += int(
            usage_payload.get("input_tokens") or usage_payload.get("inputTokens") or 0
        )
        self.tokens_out += int(
            usage_payload.get("output_tokens") or usage_payload.get("outputTokens") or 0
        )
        self.cache_read += int(
            usage_payload.get("cache_read_input_tokens")
            or usage_payload.get("cacheReadTokens")
            or 0
        )
        self.cache_write += int(
            usage_payload.get("cache_creation_input_tokens")
            or usage_payload.get("cacheWriteTokens")
            or 0
        )
        cost = usage_payload.get("total_cost_usd")
        if cost is None:
            cost = usage_payload.get("cost_usd")
        if isinstance(cost, (int, float)):
            self.cost_usd = (self.cost_usd or 0.0) + float(cost)

    def replace_usage(self, usage_payload: Mapping[str, Any] | None) -> None:
        """Replace the accumulator totals with one event's authoritative ``usage``.

        Some streams (Claude ``stream-json``, the recorded W5 fixture) emit
        ``message_start`` and ``message_delta`` events whose ``usage``
        fields roll up incrementally, then emit a final ``result`` event
        whose ``usage`` is the authoritative total. Calling ``replace_usage``
        on the ``result`` event avoids double-counting tokens and matches
        the legacy blob-parse shape that W5.7's equivalence test pins.
        """
        if not isinstance(usage_payload, dict):
            return
        self.tokens_in = int(
            usage_payload.get("input_tokens") or usage_payload.get("inputTokens") or 0
        )
        self.tokens_out = int(
            usage_payload.get("output_tokens") or usage_payload.get("outputTokens") or 0
        )
        self.cache_read = int(
            usage_payload.get("cache_read_input_tokens")
            or usage_payload.get("cacheReadTokens")
            or 0
        )
        self.cache_write = int(
            usage_payload.get("cache_creation_input_tokens")
            or usage_payload.get("cacheWriteTokens")
            or 0
        )
        cost = usage_payload.get("total_cost_usd")
        if cost is None:
            cost = usage_payload.get("cost_usd")
        if isinstance(cost, (int, float)):
            self.cost_usd = float(cost)

    def set_output(self, output: str | None) -> None:
        """Replace the run's accumulated output text (last write wins)."""
        if output is not None:
            self.final_output = output

    def to_usage(self) -> AgentUsage | None:
        """Render the accumulator as an ``AgentUsage`` if any field was set."""
        from mergecraft.agents.shared import AgentUsage

        if (
            self.tokens_in == 0
            and self.tokens_out == 0
            and self.cache_read == 0
            and self.cache_write == 0
            and self.cost_usd is None
        ):
            return None
        return AgentUsage(
            agent=self.agent_name,
            input_tokens=self.tokens_in + self.cache_read + self.cache_write,
            output_tokens=self.tokens_out,
            cache_read_tokens=self.cache_read or None,
            cache_write_tokens=self.cache_write or None,
            cost_usd=self.cost_usd,
        )


def _safe_iter_lines(stream: Iterable[str]) -> Iterator[str]:
    """Yield lines from a stdout stream, tolerating ``None`` and broken pipes."""
    for raw in stream:
        if raw is None:
            continue
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        yield text


def _resolve_active_span_for_otel_bridge() -> Span | None:
    """Return the currently active mergeCraft ``Span`` for the OTel bridge.

    The lookup is lazy (the import is deferred to the call site) so the
    stream consumer never pulls the tracer module at import time. The
    function returns ``None`` when tracing is disabled, when no span is
    active, or when the optional tracer import is unavailable — the
    result is the same as the pre-T3.2 behaviour: the handler runs
    unwrapped.
    """
    try:
        from mergecraft.tracing import tracer as _tracer_mod
        from mergecraft.tracing.tracer import Span as _Span
    except ImportError:
        return None
    active = _tracer_mod._ACTIVE_SPAN.get()
    if isinstance(active, _Span):
        return active
    return None


def _echo_line_to_stdout(line: str) -> None:
    """Echo a streamed line to ``sys.stdout`` so the activity monitor stays armed.

    The activity monitor (``utils/activity.py``) patches ``sys.stdout.write``
    to call ``mark_activity`` on every non-noise chunk. Without this echo,
    the W6 streaming read loop bypasses stdout entirely and the activity
    monitor can time out on a long, quiet run (D13). A newline is appended
    so a partial chunk still triggers the patched write.
    """
    try:
        sys.stdout.write(line)
        if not line.endswith("\n"):
            sys.stdout.write("\n")
    except Exception as exc:
        logger.debug("stream consumer stdout echo failed: {}", exc)


def consume_stream(
    *,
    raw_stream: Iterable[str],
    accumulator: StreamSpanAccumulator,
    handler: EventHandler,
) -> None:
    """Read NDJSON lines from ``raw_stream`` and dispatch each event to ``handler``.

    Args:
        raw_stream: Line iterator from a ``subprocess.Popen.stdout`` (text mode).
        accumulator: Per-run aggregator; mutated in place as events arrive.
        handler: Driver-specific callable that inspects one parsed event dict
            and emits any spans via the driver-level tracer. The handler is
            free to ignore events (``content_block_delta`` partials,
            heartbeat events) and is the right place to mutate
            ``accumulator`` (e.g. ``accumulator.absorb_usage(event["usage"])``).

    Examples:
        >>> acc = StreamSpanAccumulator(agent_name="claude")
        >>> consume_stream(raw_stream=[], accumulator=acc, handler=lambda *a, **k: None)
        >>> acc.to_usage() is None
        True
    """
    for raw_line in _safe_iter_lines(raw_stream):
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError, ValueError:
            accumulator.malformed_event_count += 1
            logger.warning("stream consumer skipped malformed line: {!r}", stripped[:200])
            continue

        if not isinstance(event, dict):
            accumulator.malformed_event_count += 1
            logger.warning("stream consumer skipped non-object event: {!r}", stripped[:200])
            continue

        accumulator.parsed_event_count += 1

        # The activity monitor is patched onto ``sys.stdout.write``. Echo
        # every well-formed line so a streaming run keeps the monitor armed
        # (D13). Malformed lines do not echo — they're noise by definition.
        _echo_line_to_stdout(stripped)

        # T3.2 — when a mergeCraft span is active, wrap the handler call in
        # ``attach_trace_context`` so any nested OTel auto-instrumented
        # operation (e.g. an ``httpx`` call inside a tool) inherits the
        # run's ``trace_id`` without the driver code having to know
        # about mergeCraft's tracer. The lookup is lazy to avoid
        # circular imports at module load time; a missing span (the
        # disabled path) leaves the handler unwrapped, exactly the
        # pre-T3.2 behaviour.
        active_span = _resolve_active_span_for_otel_bridge()
        if active_span is not None:
            try:
                from mergecraft.tracing.otel_bridge import attach_trace_context
            except ImportError:
                attach_trace_context = None  # type: ignore[assignment]
            if attach_trace_context is not None:
                try:
                    with attach_trace_context(active_span):
                        handler(accumulator, event)
                except Exception as exc:
                    logger.warning(
                        "stream consumer handler failed on event type={!r}: {}",
                        event.get("type"),
                        exc,
                    )
                continue
        try:
            handler(accumulator, event)
        except Exception as exc:
            logger.warning(
                "stream consumer handler failed on event type={!r}: {}",
                event.get("type"),
                exc,
            )


__all__ = [
    "EventHandler",
    "StreamSpanAccumulator",
    "consume_stream",
]
