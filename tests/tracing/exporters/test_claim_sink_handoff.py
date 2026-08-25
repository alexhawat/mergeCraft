"""Regression tests for ``claim_sink`` pending-handoff isolation."""

from __future__ import annotations

from mergecraft.config import RepoSettings
from mergecraft.tracing.exporters import OTLPSink, captured_payload
from mergecraft.tracing.sinks import _PENDING_SINK, MemorySink, claim_sink, sink_factory
from mergecraft.tracing.tracer import get_tracer_from_settings, reset_process_tracer_cache


def test_claim_sink_ignores_stale_memory_handoff_for_otel_settings() -> None:
    """A leftover memory ``sink_factory`` handoff must not poison OTLP export."""
    memory_settings = RepoSettings.model_validate(
        {"tracing": {"enabled": True, "sinks": [{"type": "memory"}]}}
    ).tracing
    sink_factory(memory_settings)
    assert _PENDING_SINK.get() is not None

    otel_settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [
                    {
                        "type": "otel",
                        "endpoint": "http://127.0.0.1:1/canary-claim-handoff",
                        "headers": {},
                    }
                ],
            }
        }
    )
    claimed = claim_sink(otel_settings.tracing)
    child = claimed.inner.sinks[0]
    assert isinstance(child, OTLPSink), (
        f"expected OTLPSink after discarding stale memory handoff, got {type(child).__name__}"
    )


def test_get_tracer_exports_after_stale_memory_handoff() -> None:
    """``get_tracer_from_settings`` must not route spans to a stale MemorySink."""
    memory_settings = RepoSettings.model_validate(
        {"tracing": {"enabled": True, "sinks": [{"type": "memory"}]}}
    )
    sink_factory(memory_settings.tracing)

    reset_process_tracer_cache()
    otel_settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [
                    {
                        "type": "otel",
                        "endpoint": "http://127.0.0.1:1/canary-get-tracer-handoff",
                        "headers": {},
                    }
                ],
            }
        }
    )
    tracer = get_tracer_from_settings(otel_settings)
    child = tracer.sink.inner.sinks[0]
    assert isinstance(child, OTLPSink)
    assert not isinstance(child, MemorySink)

    with tracer.start_span("tool.call", attrs_source=lambda: {"tool.name": "read_file"}):
        pass
    child.flush()
    assert len(captured_payload()) == 1
