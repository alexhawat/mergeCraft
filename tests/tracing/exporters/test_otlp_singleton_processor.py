"""RED contracts for Batch P / #293 — singleton OTLP span processors (W1).

``_setup_tracer_provider`` in ``mergecraft.tracing.exporters`` unconditionally
``add_span_processor(BatchSpanProcessor(...))`` and
``add_span_processor(_RecordingSpanProcessor())`` whenever a real
``TracerProvider`` already exists. Each ``OTLPSink`` construction (and each
MCP-style ``get_tracer_from_settings`` call that mints a fresh sink) stacks
another exporter pair on the one process-wide provider — ~29 duplicate OTLP
rows per span in production.

W2 must reuse the existing provider **without** stacking when endpoint+headers
already match (D9 sibling). These tests xfail until W2 greens them.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from loguru import logger
from tests.tracing.exporters.conftest import assert_otlp_emit_path_ready

_N_CONSTRUCTIONS = 5


def _span_processors(provider: object) -> tuple[object, ...]:
    """Return user-attached span processors regardless of OTel SDK internals."""
    composite = getattr(provider, "_active_span_processor", None)
    if composite is None:
        return ()
    return tuple(getattr(composite, "_span_processors", ()))


def _ensure_real_tracer_provider() -> None:
    """Install a real ``TracerProvider`` when OTel is still on the proxy default."""
    pytest.importorskip("opentelemetry")

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    existing = trace.get_tracer_provider()
    if type(existing).__name__ == "ProxyTracerProvider":
        trace.set_tracer_provider(TracerProvider())


def _otel_settings_dict() -> dict[str, Any]:
    return {
        "tracing": {
            "enabled": True,
            "sinks": [
                {
                    "type": "otel",
                    "endpoint": "http://127.0.0.1:1/canary-singleton-processor",
                    "headers": {},
                }
            ],
        }
    }


@pytest.mark.parametrize("construction_count", [_N_CONSTRUCTIONS])
def test_setup_tracer_provider_stacks_at_most_one_batch_processor(
    construction_count: int,
) -> None:
    """N ``_setup_tracer_provider`` calls with the same endpoint attach one BatchSpanProcessor."""
    pytest.importorskip("opentelemetry")

    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    import mergecraft.tracing.exporters as exporters
    from mergecraft.tracing.exporters import _otlp_exporter_matches

    exporters._reset_test_seam()
    _ensure_real_tracer_provider()
    endpoint = "http://127.0.0.1:1/canary-singleton-batch-processor"
    headers: dict[str, str] = {}

    for _ in range(construction_count):
        exporters._setup_tracer_provider(
            endpoint=endpoint,
            headers=headers,
            service_name="mergecraft-otel",
        )

    from opentelemetry import trace

    provider = trace.get_tracer_provider()
    processors = _span_processors(provider)
    batch_processors = [
        processor
        for processor in processors
        if isinstance(processor, BatchSpanProcessor)
        and _otlp_exporter_matches(
            getattr(processor, "span_exporter", None),
            endpoint=endpoint,
            headers=headers,
        )
    ]
    recording_processors = [
        processor
        for processor in processors
        if isinstance(processor, exporters._RecordingSpanProcessor)
    ]

    assert len(batch_processors) == 1, (
        "expected exactly one OTLP BatchSpanProcessor on the shared provider, "
        f"got {len(batch_processors)} after {construction_count} setup calls"
    )
    assert len(recording_processors) == 1, (
        "expected exactly one recording test-seam processor, "
        f"got {len(recording_processors)} after {construction_count} setup calls"
    )


@pytest.mark.parametrize("construction_count", [_N_CONSTRUCTIONS])
def test_n_otlp_sinks_export_one_payload_per_span(
    construction_count: int,
    trace_event_payload: dict[str, Any],
) -> None:
    """N ``OTLPSink`` constructions against one endpoint yield one ``captured_payload`` per span."""
    pytest.importorskip("opentelemetry")

    from mergecraft.tracing import TraceEvent
    from mergecraft.tracing.exporters import OTLPSink, _reset_test_seam, captured_payload

    _ensure_real_tracer_provider()
    endpoint = "http://127.0.0.1:1/canary-singleton-otlp-sinks"
    headers: dict[str, str] = {}

    sinks: list[OTLPSink] = []
    for _ in range(construction_count):
        sink = OTLPSink(endpoint=endpoint, headers=headers, service_name="mergecraft-otel")
        sink._ensure_provider()
        sinks.append(sink)

    _reset_test_seam()
    event = TraceEvent.model_validate(trace_event_payload | {"span_id": "singleton-p"})
    sinks[-1].write(event)
    sinks[-1].flush()

    payloads = captured_payload()
    assert len(payloads) == 1, (
        "one span must produce exactly one recorded OTLP payload, "
        f"got {len(payloads)} after {construction_count} sink constructions"
    )
    parsed = json.loads(b"".join(payloads).decode("utf-8"))
    assert parsed[0]["name"] == trace_event_payload["kind"]


@pytest.mark.parametrize("construction_count", [_N_CONSTRUCTIONS])
def test_get_tracer_from_settings_does_not_multiply_otlp_exports(
    construction_count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP-style repeated ``get_tracer_from_settings`` calls export each span once."""
    pytest.importorskip("opentelemetry")

    from mergecraft.config import RepoSettings
    from mergecraft.tracing.exporters import _reset_test_seam, captured_payload
    from mergecraft.tracing.tracer import get_tracer_from_settings, reset_process_tracer_cache

    _ensure_real_tracer_provider()
    reset_process_tracer_cache()
    _reset_test_seam()
    monkeypatch.setenv("MERGECRAFT_TRACING", "true")
    endpoint = "http://127.0.0.1:1/canary-singleton-get-tracer"
    monkeypatch.setenv("MERGECRAFT_OTEL_ENDPOINT", endpoint)

    settings = RepoSettings.model_validate(
        _otel_settings_dict()
        | {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "otel", "endpoint": endpoint, "headers": {}}],
            }
        }
    )
    tracers = [get_tracer_from_settings(settings) for _ in range(construction_count)]

    reset_process_tracer_cache()
    _reset_test_seam()
    assert_otlp_emit_path_ready(tracers[-1])

    warning_messages: list[str] = []
    warning_sink_id = logger.add(
        lambda record: warning_messages.append(record["message"]),
        level="WARNING",
        filter=lambda record: "trace otel sink write failed" in record["message"],
    )
    try:
        with tracers[-1].start_span(
            "tool.call",
            attrs_source=lambda: {"tool.name": "read_file", "tool.exit_code": "ok"},
        ):
            pass
    finally:
        logger.remove(warning_sink_id)

    flush = getattr(tracers[-1].sink, "flush", None)
    if callable(flush):
        flush()

    assert not warning_messages, (
        f"OTLPSink.write must not swallow export failures silently; warnings: {warning_messages!r}"
    )

    payloads = captured_payload()
    assert len(payloads) == 1, (
        "one tool.call span must produce exactly one OTLP payload, "
        f"got {len(payloads)} after {construction_count} tracer constructions"
    )


def _otlp_batch_processors(endpoint: str) -> list[object]:
    """Return the OTLP ``BatchSpanProcessor`` s on the shared provider for *endpoint*."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    return [
        processor
        for processor in _span_processors(trace.get_tracer_provider())
        if isinstance(processor, BatchSpanProcessor)
        and getattr(getattr(processor, "span_exporter", None), "_endpoint", None) == endpoint
    ]


def _construct_repeatedly(endpoint: str, headers: dict[str, str]) -> None:
    import mergecraft.tracing.exporters as exporters

    exporters._reset_test_seam()
    _ensure_real_tracer_provider()
    for _ in range(_N_CONSTRUCTIONS):
        exporters._setup_tracer_provider(
            endpoint=endpoint, headers=headers, service_name="mergecraft-otel"
        )


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({"authorization": "Bearer x"}, id="lowercase"),
        pytest.param({"Authorization": "Bearer x", "X-Api-Key": "k"}, id="mixed-case"),
    ],
)
@pytest.mark.parametrize(
    "env",
    [
        pytest.param({}, id="no-env"),
        pytest.param({"OTEL_EXPORTER_OTLP_COMPRESSION": "gzip"}, id="compression"),
        pytest.param({"OTEL_EXPORTER_OTLP_HEADERS": "x-env=1,x-team=a"}, id="env-headers"),
        pytest.param(
            {
                "OTEL_EXPORTER_OTLP_COMPRESSION": "gzip",
                "OTEL_EXPORTER_OTLP_TRACES_HEADERS": "x-env=1",
            },
            id="compression-and-traces-headers",
        ),
    ],
)
def test_real_exporter_is_reused_whatever_the_header_case_or_otlp_env(
    headers: dict[str, str], env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """OTel 1.45 lowercases header names and merges env headers; reuse must still hold (#293)."""
    pytest.importorskip("opentelemetry")

    for name, value in env.items():
        monkeypatch.setenv(name, value)
    endpoint = f"http://127.0.0.1:1/canary-reuse-{abs(hash((tuple(headers), tuple(env))))}"

    _construct_repeatedly(endpoint, headers)

    assert len(_otlp_batch_processors(endpoint)) == 1


def test_a_different_header_value_gets_its_own_exporter() -> None:
    """Same endpoint, different credential: the old exporter must not be reused."""
    pytest.importorskip("opentelemetry")

    endpoint = "http://127.0.0.1:1/canary-different-credential"
    _construct_repeatedly(endpoint, {"Authorization": "Bearer one"})
    _construct_repeatedly(endpoint, {"authorization": "Bearer two"})

    sent = sorted(
        _exporter_header(processor, "authorization")
        for processor in _otlp_batch_processors(endpoint)
    )
    assert sent == ["Bearer one", "Bearer two"]


def test_an_exporter_with_unconfigured_credentials_is_not_reused() -> None:
    """An exporter carrying an auth header mergeCraft did not configure stays out of reuse."""
    pytest.importorskip("opentelemetry")

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    from mergecraft.tracing.exporters import _otlp_exporter_matches

    endpoint = "http://127.0.0.1:1/canary-extra-credential"
    exporter = OTLPSpanExporter(
        endpoint=endpoint, headers={"authorization": "Bearer x", "x-api-key": "other"}
    )

    assert not _otlp_exporter_matches(
        exporter, endpoint=endpoint, headers={"authorization": "Bearer x"}
    )
    assert _otlp_exporter_matches(
        exporter,
        endpoint=endpoint,
        headers={"Authorization": "Bearer x", "X-Api-Key": "other"},
    )


def _exporter_header(processor: object, name: str) -> str:
    from mergecraft.tracing.exporters import _otlp_exporter_headers

    return _otlp_exporter_headers(getattr(processor, "span_exporter", None))[name]
