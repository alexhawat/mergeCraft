"""RED contracts for Batch BB / #373 — real OTLP span duration (W3).

``OTLPSink.write`` currently calls ``start_span`` then ``span.end()`` at export
time with no ``start_time`` / ``end_time``. Logfire therefore shows zero-width
spans (~15µs) even when ``TraceEvent.ts_end_ns - ts_start_ns`` is seconds of
provider wall time. The ``duration_ms`` attribute carries the real interval but
OTel timestamps are the source of truth for Logfire duration (D9/D10).

W4 passes ``event.ts_start_ns`` / ``event.ts_end_ns`` into OTel. This test
xfails until W4 greens it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

_CANARY_ENDPOINT = "http://127.0.0.1:1/canary-373-span-duration"
_EPOCH_START_NS = 1_700_000_000_000_000_000
# Production symptom: export-time start+end yields ~15µs, not provider wall time.
_ZERO_WIDTH_CEILING_NS = 100_000


def _ensure_real_tracer_provider() -> None:
    """Install a real ``TracerProvider`` when OTel is still on the proxy default."""
    pytest.importorskip("opentelemetry")

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    existing = trace.get_tracer_provider()
    if type(existing).__name__ == "ProxyTracerProvider":
        trace.set_tracer_provider(TracerProvider())


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


def _export_event_via_otlp_sink(event: Any) -> dict[str, Any]:
    """Write ``event`` through a fresh OTLP sink and return the recorded span."""
    from mergecraft.tracing.exporters import OTLPSink, _reset_test_seam

    _ensure_real_tracer_provider()
    _reset_test_seam()
    sink = OTLPSink(
        endpoint=_CANARY_ENDPOINT,
        headers={},
        service_name="mergecraft-otel-duration-373",
    )
    sink.write(event)
    sink.flush()

    spans = _recorded_spans()
    assert len(spans) == 1, f"expected exactly one recorded span, got {len(spans)}"
    return spans[0]


@pytest.mark.parametrize("wall_seconds", [1, 3])
def test_exported_span_duration_matches_trace_event_wall_time(
    trace_event_payload: dict[str, Any],
    wall_seconds: int,
) -> None:
    """``ts_end_ns - ts_start_ns`` wall time must appear as OTel span duration, not ~15µs."""
    pytest.importorskip("opentelemetry")

    from mergecraft.tracing import TraceEvent

    expected_duration_ns = wall_seconds * 1_000_000_000
    ts_start_ns = _EPOCH_START_NS
    ts_end_ns = ts_start_ns + expected_duration_ns

    event = TraceEvent.model_validate(
        trace_event_payload
        | {
            "span_id": f"373-duration-{wall_seconds}s",
            "ts_start_ns": ts_start_ns,
            "ts_end_ns": ts_end_ns,
        }
    )
    recorded = _export_event_via_otlp_sink(event)

    start_time = recorded.get("start_time")
    end_time = recorded.get("end_time")
    assert start_time is not None, "recording seam must surface OTel start_time on exported spans"
    assert end_time is not None, "recording seam must surface OTel end_time on exported spans"

    actual_duration_ns = int(end_time) - int(start_time)
    assert actual_duration_ns > _ZERO_WIDTH_CEILING_NS, (
        "exported span is zero-width today (~15µs); OTLPSink.write must pass "
        f"TraceEvent ts_start_ns/ts_end_ns into OTel (got {actual_duration_ns} ns)"
    )
    assert actual_duration_ns == expected_duration_ns, (
        "OTel span duration must equal TraceEvent wall time "
        f"(expected {expected_duration_ns} ns, got {actual_duration_ns} ns)"
    )
