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

import json
from typing import Any

import pytest

_N_WRITES = 5
_SHARED_ENDPOINT = "http://127.0.0.1:1/canary-372-endpoint-dedupe"


def _ensure_real_tracer_provider() -> None:
    """Install a real ``TracerProvider`` when OTel is still on the proxy default."""
    pytest.importorskip("opentelemetry")

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    existing = trace.get_tracer_provider()
    if type(existing).__name__ == "ProxyTracerProvider":
        trace.set_tracer_provider(TracerProvider())


def _shared_endpoint_settings_dict(*, endpoint: str, token: str) -> dict[str, Any]:
    """Tracing config with logfire + otel aimed at the same OTLP destination."""
    auth = {"authorization": f"Bearer {token}"}
    return {
        "tracing": {
            "enabled": True,
            "sinks": [
                {
                    "type": "logfire",
                    "tokenRef": "MERGECRAFT_LOGFIRE_TOKEN",
                    "endpoint": endpoint,
                },
                {
                    "type": "otel",
                    "endpoint": endpoint,
                    "headers": auth,
                },
            ],
        }
    }


def _recorded_spans() -> list[dict[str, Any]]:
    """Parse every JSON-array chunk the recording processor appended."""
    from mergecraft.tracing.exporters import captured_payload

    spans: list[dict[str, Any]] = []
    for chunk in captured_payload():
        parsed = json.loads(chunk.decode("utf-8"))
        if isinstance(parsed, list):
            spans.extend(parsed)
        else:
            spans.append(parsed)
    return spans


def _otlp_sink_children(sink: Any) -> list[Any]:
    """Return live :class:`OTLPSink` children under the redacting wrapper."""
    from mergecraft.tracing.exporters import OTLPSink

    inner = getattr(sink, "inner", sink)
    children = getattr(inner, "sinks", ())
    return [child for child in children if isinstance(child, OTLPSink)]


def _export_span_count(event: Any, otlp_sinks: list[Any]) -> int:
    """Count recorded spans when each resolved OTLP sink exports ``event`` once.

    The recording seam resets between provider initialisations, so a
    ``MultiSink.write`` under-counts duplicate sinks. Summing per resolved sink
    matches production fan-out (N sinks -> N identical spans).
    """
    from mergecraft.tracing.exporters import _reset_test_seam

    total = 0
    for child in otlp_sinks:
        _reset_test_seam()
        child.write(event)
        child.flush()
        total += len(_recorded_spans())
    return total


def _build_sink(
    monkeypatch: pytest.MonkeyPatch,
    *,
    endpoint: str = _SHARED_ENDPOINT,
    token: str = "test-token-372-dedupe",
) -> Any:
    pytest.importorskip("logfire")
    pytest.importorskip("opentelemetry")

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import sink_factory

    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", token)
    settings = RepoSettings.model_validate(
        _shared_endpoint_settings_dict(endpoint=endpoint, token=token)
    )
    _ensure_real_tracer_provider()
    return sink_factory(settings.tracing)


@pytest.mark.xfail(reason="green after W2: #372 OTLP sink dedupe by endpoint", strict=False)
def test_logfire_and_otel_shared_endpoint_exports_one_span_per_event(
    monkeypatch: pytest.MonkeyPatch,
    trace_event_payload: dict[str, Any],
) -> None:
    """One ``TraceEvent`` with logfire+otel (same endpoint) exports exactly one span."""
    from mergecraft.tracing import TraceEvent

    sink = _build_sink(monkeypatch)
    otlp_sinks = _otlp_sink_children(sink)
    assert len(otlp_sinks) == 1, (
        "logfire+otel aimed at the same endpoint must resolve to one OTLPSink, "
        f"got {len(otlp_sinks)}"
    )

    event = TraceEvent.model_validate(trace_event_payload | {"span_id": "372-one-span"})
    span_total = _export_span_count(event, otlp_sinks)
    assert span_total == 1, (
        "one TraceEvent must produce exactly one OTLP span when logfire and otel "
        f"share an endpoint, got {span_total} spans across {len(otlp_sinks)} sinks"
    )


@pytest.mark.parametrize("write_count", [_N_WRITES])
@pytest.mark.xfail(reason="green after W2: #372 OTLP sink dedupe by endpoint", strict=False)
def test_otlp_sink_list_does_not_grow_across_writes(
    monkeypatch: pytest.MonkeyPatch,
    trace_event_payload: dict[str, Any],
    write_count: int,
) -> None:
    """Resolved OTLP sinks stay deduped — the child list must not grow per write."""
    from mergecraft.tracing import TraceEvent

    sink = _build_sink(monkeypatch)
    initial_otlp_sinks = _otlp_sink_children(sink)
    assert len(initial_otlp_sinks) == 1, (
        "logfire+otel aimed at the same endpoint must resolve to one OTLPSink, "
        f"got {len(initial_otlp_sinks)}"
    )

    per_write_span_counts: list[int] = []
    for index in range(write_count):
        event = TraceEvent.model_validate(trace_event_payload | {"span_id": f"372-write-{index}"})
        per_write_span_counts.append(_export_span_count(event, initial_otlp_sinks))
        assert len(_otlp_sink_children(sink)) == len(initial_otlp_sinks), (
            "OTLP sink list must not grow across writes in one process; "
            f"after write {index + 1} expected {len(initial_otlp_sinks)}, "
            f"got {len(_otlp_sink_children(sink))}"
        )

    assert all(count == 1 for count in per_write_span_counts), (
        "each write must export exactly one span after dedupe, "
        f"got per-write counts {per_write_span_counts}"
    )
