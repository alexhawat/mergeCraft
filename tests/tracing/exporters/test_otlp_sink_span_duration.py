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

from typing import Any

import pytest
from tests.tracing.exporters.conftest import export_event_via_otlp_sink

_CANARY_ENDPOINT = "http://127.0.0.1:1/canary-373-span-duration"
_EPOCH_START_NS = 1_700_000_000_000_000_000
# Production symptom: export-time start+end yields ~15µs, not provider wall time.
_ZERO_WIDTH_CEILING_NS = 100_000


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
    recorded = export_event_via_otlp_sink(
        event,
        endpoint=_CANARY_ENDPOINT,
        service_name="mergecraft-otel-duration-373",
    )

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
