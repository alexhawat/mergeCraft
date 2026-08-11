"""Regression tests for the Logfire/OTLP tracer-provider fix.

Two defects were fixed in ``mergecraft.tracing.exporters``:

1. ``_setup_tracer_provider`` called ``set_tracer_provider`` unguarded. When a
   real ``TracerProvider`` was already installed (``logfire`` activates its own
   on import; a prior sink may have set one), OTel raised
   ``Overriding of current TracerProvider is not allowed``. The surrounding
   ``try/except`` swallowed it and returned ``None`` — silently turning the
   sink into a no-op so spans never exported.

2. The provider only carried the in-memory ``_RecordingSpanProcessor`` (a test
   seam) and never attached the real ``OTLPSpanExporter`` — so even after the
   override was fixed, spans would never reach Logfire.

These tests pin both halves.
"""

from __future__ import annotations

import pytest

import mergecraft.tracing.exporters as exporters


def _span_processors(provider: object) -> tuple[object, ...]:
    """Read the attached span processors regardless of OTel SDK internals.

    The SDK stores processors on ``provider._active_span_processor`` (a
    ``SynchronousMultiSpanProcessor``) whose ``_span_processors`` is the tuple
    of user-added processors. We assert on that tuple rather than the
    non-existent ``_active_span_processors`` plural attribute.
    """
    composite = getattr(provider, "_active_span_processor", None)
    if composite is None:
        return ()
    return tuple(getattr(composite, "_span_processors", ()))


def test_set_tracer_provider_reuses_existing_provider() -> None:
    """When ``set_tracer_provider`` would override, the provider is reused, not None.

    Monkeypatch ``trace.set_tracer_provider`` to raise the OTel override error
    on the first call (mimicking a provider already installed by ``logfire``).
    ``_setup_tracer_provider`` must still return a non-None provider and attach
    a ``_RecordingSpanProcessor`` so the test seam keeps working.
    """
    pytest.importorskip("logfire")
    pytest.importorskip("opentelemetry")

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    original = trace.set_tracer_provider

    def _raise_once(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Overriding of current TracerProvider is not allowed")

    # Install a real provider first (as logfire would), then make the next
    # set_tracer_provider attempt raise the override error.
    trace.set_tracer_provider(TracerProvider())
    trace.set_tracer_provider = _raise_once  # type: ignore[assignment]
    try:
        provider = exporters._setup_tracer_provider(
            endpoint="https://logfire.pydantic.dev/api/v1/otlp/v1/traces",
            headers={"authorization": "Bearer pylf_test_aaa"},
            service_name="mergecraft-logfire",
        )
    finally:
        trace.set_tracer_provider = original  # type: ignore[assignment]

    assert provider is not None, "override guard must reuse an existing provider, not return None"
    assert any(
        isinstance(p, exporters._RecordingSpanProcessor) for p in _span_processors(provider)
    ), "reused provider must still carry the recording processor (test seam)"
    assert exporters.has_active_tracer_provider()


def test_logfire_sink_exports_to_otlp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A logfire entry with a resolved token yields a live OTLPSink that wires an exporter.

    Asserts ``build_remote_sink`` returns an ``OTLPSink`` (not ``NullSink``)
    when a token is resolved, and that a real ``OTLPSpanExporter``-backed
    ``BatchSpanProcessor`` is attached to the provider (the production export
    path to Logfire), while the override guard does not raise.
    """
    pytest.importorskip("logfire")
    pytest.importorskip("opentelemetry")

    # A resolved (fake) token is required for the sink to be live.
    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", "pylf_test_logfire_export")

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import NullSink, sink_factory
    from mergecraft.tracing.exporters import OTLPSink

    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "logfire", "tokenRef": "MERGECRAFT_LOGFIRE_TOKEN"}],
            }
        }
    ).tracing
    sink = sink_factory(settings)
    # sink_factory wraps the live sink in RedactingSink(MultiSink([...])).
    inner = sink.inner.sinks[0]
    assert not isinstance(inner, NullSink)
    assert isinstance(inner, OTLPSink)

    # Build a real span so the provider is constructed, then inspect it.
    from mergecraft.tracing import TraceEvent

    event = TraceEvent.model_validate(
        {
            "kind": "llm.call",
            "span_id": "fix-1",
            "parent_span_id": None,
            "session_id": "fix-run",
            "turn_id": "t",
            "tier": "trusted",
            "ts_start_ns": 0,
            "ts_end_ns": 1,
            "status": "ok",
            "attrs": {},
        }
    )
    inner.write(event)
    provider = inner._provider
    assert provider is not None
    processors = _span_processors(provider)
    real_exporters = [
        sp
        for sp in processors
        if isinstance(sp, BatchSpanProcessor)
        and isinstance(getattr(sp, "span_exporter", None), OTLPSpanExporter)
    ]
    assert real_exporters, "a real OTLPSpanExporter-backed span processor must be attached"
    assert any(isinstance(sp, exporters._RecordingSpanProcessor) for sp in processors), (
        "the recording test seam must still be attached"
    )


def test_logfire_sink_null_when_no_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No token resolves → NullSink (existing behaviour preserved)."""
    pytest.importorskip("logfire")

    monkeypatch.delenv("MERGECRAFT_LOGFIRE_TOKEN", raising=False)

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import NullSink, sink_factory

    settings = RepoSettings.model_validate(
        {"tracing": {"enabled": True, "sinks": [{"type": "logfire", "project": "demo"}]}}
    ).tracing
    sink = sink_factory(settings)
    # sink_factory wraps the no-op in RedactingSink(MultiSink([NullSink])).
    assert isinstance(sink.inner.sinks[0], NullSink)
