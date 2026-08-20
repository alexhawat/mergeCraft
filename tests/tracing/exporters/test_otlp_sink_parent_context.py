"""RED contracts for Batch BC / #374 — OTel parent context + span_id (W5).

``OTLPSink.write`` currently writes ``parent_span_id`` as a string attribute only
and never passes ``context=`` to ``start_span``. ``_override_span_trace_id`` rewrites
``trace_id`` but keeps the SDK-generated ``span_id``. Logfire therefore shows every
span as a root with mismatched column vs attribute ids.

W6 overrides ``span_id`` from the event, builds parent ``SpanContext``, and passes
``context=`` into ``start_span``. These tests xfail until W6 greens them.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from tests.tracing.exporters.conftest import export_events_via_otlp_sink

_CANARY_ENDPOINT = "http://127.0.0.1:1/canary-374-parent-context"
_TRACE_ID_HEX = "37400000000000000000000000000001"
_PARENT_SPAN_ID = "37400000000000000000000000000001"
_CHILD_SPAN_ID = "37400000000000000000000000000002"


@pytest.fixture(autouse=True)
def _enrich_recording_with_span_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Augment the recording seam with OTel ``span_id`` / parent from ``SpanContext``.

    Production Logfire reads column ids from OTel context, not mergeCraft attrs.
    W6 may extend ``_RecordingSpanProcessor``; until then tests enrich the last
    captured payload so RED contracts assert on real OTel identifiers.
    """
    pytest.importorskip("opentelemetry")

    from mergecraft.tracing import exporters

    original_on_end = exporters._RecordingSpanProcessor.on_end

    def enriched_on_end(self: Any, span: Any) -> None:
        original_on_end(self, span)
        if not exporters._RECORDING_PAYLOADS:
            return
        chunk = exporters._RECORDING_PAYLOADS[-1]
        parsed = json.loads(chunk.decode("utf-8"))
        payload = parsed[0] if isinstance(parsed, list) else parsed

        span_ctx = span.get_span_context()
        payload["otel_span_id"] = format(int(span_ctx.span_id), "016x")

        parent = getattr(span, "parent", None)
        payload["otel_parent_span_id"] = (
            format(int(parent.span_id), "016x") if parent is not None else None
        )

        exporters._RECORDING_PAYLOADS[-1] = b"[" + exporters.json_dumps(payload) + b"]"

    monkeypatch.setattr(exporters._RecordingSpanProcessor, "on_end", enriched_on_end)


def _mergecraft_otel_span_id(mergecraft_span_id: str) -> str:
    """Map mergeCraft ``span_id`` to the OTel width W6 will use (issue #374)."""
    return mergecraft_span_id[:16]


def test_child_export_carries_otel_parent_and_mergecraft_span_id(
    trace_event_payload: dict[str, Any],
) -> None:
    """Child ``TraceEvent`` must link to parent OTel ``span_id`` and carry event ``span_id``."""
    pytest.importorskip("opentelemetry")

    from mergecraft.tracing import TraceEvent

    parent_event = TraceEvent.model_validate(
        trace_event_payload
        | {
            "kind": "provider.call",
            "span_id": _PARENT_SPAN_ID,
            "parent_span_id": None,
            "trace_id": _TRACE_ID_HEX,
        }
    )
    child_event = TraceEvent.model_validate(
        trace_event_payload
        | {
            "kind": "llm.call",
            "span_id": _CHILD_SPAN_ID,
            "parent_span_id": _PARENT_SPAN_ID,
            "trace_id": _TRACE_ID_HEX,
        }
    )

    parent_recorded, child_recorded = export_events_via_otlp_sink(
        [parent_event, child_event],
        endpoint=_CANARY_ENDPOINT,
        service_name="mergecraft-otel-parent-374",
    )

    expected_parent_otel = _mergecraft_otel_span_id(_PARENT_SPAN_ID)
    expected_child_otel = _mergecraft_otel_span_id(_CHILD_SPAN_ID)

    assert parent_recorded["otel_parent_span_id"] is None, (
        "root provider.call must have no OTel parent context"
    )
    assert parent_recorded["otel_span_id"] == expected_parent_otel, (
        "exported OTel span_id must equal mergeCraft event.span_id (first 16 hex chars); "
        f"expected {expected_parent_otel!r}, got {parent_recorded['otel_span_id']!r}"
    )

    assert child_recorded["otel_span_id"] == expected_child_otel, (
        "exported OTel span_id must equal mergeCraft event.span_id (first 16 hex chars); "
        f"expected {expected_child_otel!r}, got {child_recorded['otel_span_id']!r}"
    )
    assert child_recorded["otel_parent_span_id"] == expected_parent_otel, (
        "child span OTel parent must equal parent span's OTel span_id; "
        f"expected {expected_parent_otel!r}, got {child_recorded['otel_parent_span_id']!r}"
    )
