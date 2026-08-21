"""RED contracts for Batch BA / #372 — dedupe OTLP sinks by endpoint (W1).

When ``logfire`` and ``otel`` both resolve to the same OTLP endpoint (+ headers),
``sink_factory`` must fan out through **one** :class:`OTLPSink`, not two. Today
``MultiSink`` carries one sink per config entry, so one ``TraceEvent`` produces
N identical ``llm.call`` rows (the production 3-29x multiplier when processors
also stack).

W2 dedupes by resolved endpoint per D11 without weakening the #293 processor
guard. These tests xfail until W2 greens them.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.tracing.exporters.conftest import (
    build_deduped_otlp_sink,
    export_span_count,
    otlp_sink_children,
)

_N_WRITES = 5
_SHARED_ENDPOINT = "http://127.0.0.1:1/canary-372-endpoint-dedupe"


def test_logfire_and_otel_shared_endpoint_exports_one_span_per_event(
    monkeypatch: pytest.MonkeyPatch,
    trace_event_payload: dict[str, Any],
) -> None:
    """One ``TraceEvent`` with logfire+otel (same endpoint) exports exactly one span."""
    from mergecraft.tracing import TraceEvent

    sink = build_deduped_otlp_sink(
        monkeypatch,
        endpoint=_SHARED_ENDPOINT,
        token="test-token-372-dedupe",
    )
    otlp_sinks = otlp_sink_children(sink)
    assert len(otlp_sinks) == 1, (
        "logfire+otel aimed at the same endpoint must resolve to one OTLPSink, "
        f"got {len(otlp_sinks)}"
    )

    event = TraceEvent.model_validate(trace_event_payload | {"span_id": "372-one-span"})
    span_total = export_span_count(event, otlp_sinks)
    assert span_total == 1, (
        "one TraceEvent must produce exactly one OTLP span when logfire and otel "
        f"share an endpoint, got {span_total} spans across {len(otlp_sinks)} sinks"
    )


@pytest.mark.parametrize("write_count", [_N_WRITES])
def test_otlp_sink_list_does_not_grow_across_writes(
    monkeypatch: pytest.MonkeyPatch,
    trace_event_payload: dict[str, Any],
    write_count: int,
) -> None:
    """Resolved OTLP sinks stay deduped — the child list must not grow per write."""
    from mergecraft.tracing import TraceEvent

    sink = build_deduped_otlp_sink(
        monkeypatch,
        endpoint=_SHARED_ENDPOINT,
        token="test-token-372-dedupe",
    )
    initial_otlp_sinks = otlp_sink_children(sink)
    assert len(initial_otlp_sinks) == 1, (
        "logfire+otel aimed at the same endpoint must resolve to one OTLPSink, "
        f"got {len(initial_otlp_sinks)}"
    )

    per_write_span_counts: list[int] = []
    for index in range(write_count):
        event = TraceEvent.model_validate(trace_event_payload | {"span_id": f"372-write-{index}"})
        per_write_span_counts.append(export_span_count(event, initial_otlp_sinks))
        assert len(otlp_sink_children(sink)) == len(initial_otlp_sinks), (
            "OTLP sink list must not grow across writes in one process; "
            f"after write {index + 1} expected {len(initial_otlp_sinks)}, "
            f"got {len(otlp_sink_children(sink))}"
        )

    assert all(count == 1 for count in per_write_span_counts), (
        "each write must export exactly one span after dedupe, "
        f"got per-write counts {per_write_span_counts}"
    )


def test_otlp_sink_dedupe_normalizes_header_key_case() -> None:
    """``Authorization`` and ``authorization`` on the same endpoint dedupe to one sink (#372)."""
    from mergecraft.tracing.exporters import OTLPSink, dedupe_otlp_sinks

    endpoint = _SHARED_ENDPOINT
    token = "Bearer test-token-372-header-case"
    sink_a = OTLPSink(endpoint=endpoint, headers={"Authorization": token})
    sink_b = OTLPSink(endpoint=endpoint, headers={"authorization": token})

    deduped = dedupe_otlp_sinks([sink_a, sink_b])

    assert len(deduped) == 1, (
        f"header keys must dedupe case-insensitively; expected 1 OTLPSink, got {len(deduped)}"
    )
