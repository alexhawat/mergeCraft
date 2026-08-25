"""Shared fixtures for Batch D exporter tests (W7).

The exporters are reachable through the ``mergecraft.tracing.exporters`` module
that W8 ships — they live behind the optional ``[tracing]`` extra and import
``logfire`` / ``opentelemetry`` lazily (D6). Tests that genuinely need the
exporter classes use :func:`pytest.importorskip` and pin behaviour under the
installed path; tests for the uninstalled path (W7.5) verify the resolver
fails closed without raising an unhandled ``ImportError``.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _reset_exporter_tracer_cache() -> Iterator[None]:
    """Clear process tracer cache and active span before each exporter test.

    ``tests/conftest.py`` already autouses ``reset_process_tracer_cache`` globally;
    this package repeats it so OTLP singleton tests never inherit a stale
    ``_ACTIVE_SPAN`` from a sibling exporter test on the same xdist worker.
    Also clears any stale ``sink_factory`` handoff left by memory/jsonl tests.
    Resets enterprise telemetry binding so a prior ``telemetry: opt-out`` test
    does not block OTLP export on the same worker.
    """
    from mergecraft.enterprise.runtime import reset_enterprise_runtime
    from mergecraft.tracing.sinks import _PENDING_SINK
    from mergecraft.tracing.tracer import reset_process_tracer_cache

    reset_enterprise_runtime()
    reset_process_tracer_cache()
    _PENDING_SINK.set(None)
    yield
    reset_enterprise_runtime()
    reset_process_tracer_cache()
    _PENDING_SINK.set(None)


def ensure_real_tracer_provider() -> None:
    """Install a real ``TracerProvider`` when OTel is still on the proxy default."""
    pytest.importorskip("opentelemetry")

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    existing = trace.get_tracer_provider()
    if type(existing).__name__ == "ProxyTracerProvider":
        trace.set_tracer_provider(TracerProvider())


def recorded_spans() -> list[dict[str, Any]]:
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


def export_events_via_otlp_sink(
    events: list[Any],
    *,
    endpoint: str,
    service_name: str,
) -> list[dict[str, Any]]:
    """Write ``events`` through a fresh OTLP sink and return recorded spans in order."""
    from mergecraft.tracing.exporters import OTLPSink, _reset_test_seam

    ensure_real_tracer_provider()
    _reset_test_seam()
    sink = OTLPSink(
        endpoint=endpoint,
        headers={},
        service_name=service_name,
    )
    for event in events:
        sink.write(event)
    sink.flush()

    spans = recorded_spans()
    assert len(spans) == len(events), f"expected {len(events)} recorded spans, got {len(spans)}"
    return spans


def export_event_via_otlp_sink(
    event: Any,
    *,
    endpoint: str,
    service_name: str,
) -> dict[str, Any]:
    """Write ``event`` through a fresh OTLP sink and return the recorded span."""
    spans = export_events_via_otlp_sink([event], endpoint=endpoint, service_name=service_name)
    assert len(spans) == 1, f"expected exactly one recorded span, got {len(spans)}"
    return spans[0]


def otlp_sink_children(sink: Any) -> list[Any]:
    """Return live :class:`OTLPSink` children under the redacting wrapper."""
    from mergecraft.tracing.exporters import OTLPSink

    inner = getattr(sink, "inner", sink)
    children = getattr(inner, "sinks", ())
    return [child for child in children if isinstance(child, OTLPSink)]


def assert_otlp_emit_path_ready(tracer: Any) -> Any:
    """Assert the tracer resolves to a live OTLP sink with an active provider.

    Raises:
        AssertionError: When the sink is degraded, not OTLP, or the provider
            or tracer is missing after lazy initialization.
    """
    from mergecraft.tracing.exporters import OTLPSink, has_active_tracer_provider
    from mergecraft.tracing.sinks import NullSink

    sink = getattr(tracer, "sink", tracer)
    inner = getattr(sink, "inner", sink)
    children = list(getattr(inner, "sinks", ()))
    assert children, "tracer sink must expose at least one child sink"
    assert not any(isinstance(child, NullSink) for child in children), (
        "expected a live OTLP sink, got NullSink (remote export disabled or extra missing)"
    )
    otlp_sinks = [child for child in children if isinstance(child, OTLPSink)]
    assert len(otlp_sinks) == 1, (
        f"expected exactly one OTLPSink child, got {[type(c).__name__ for c in children]}"
    )
    otlp_sink = otlp_sinks[0]
    provider = otlp_sink._ensure_provider()
    assert provider is not None, "OTLPSink provider setup must not degrade to None"
    assert otlp_sink._tracer is not None, "OTLPSink tracer must be bound after provider setup"
    assert has_active_tracer_provider(), (
        "has_active_tracer_provider() must be True once the OTLP provider is wired"
    )
    return otlp_sink


def export_span_count(event: Any, otlp_sinks: list[Any]) -> int:
    """Count recorded spans when each resolved OTLP sink exports ``event`` once."""
    from mergecraft.tracing.exporters import _reset_test_seam

    total = 0
    for child in otlp_sinks:
        _reset_test_seam()
        child.write(event)
        child.flush()
        total += len(recorded_spans())
    return total


def shared_endpoint_settings_dict(*, endpoint: str, token: str) -> dict[str, Any]:
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


def build_deduped_otlp_sink(
    monkeypatch: pytest.MonkeyPatch,
    *,
    endpoint: str,
    token: str,
) -> Any:
    """Resolve a sink factory product with logfire + otel on the same endpoint."""
    pytest.importorskip("logfire")
    pytest.importorskip("opentelemetry")

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import sink_factory

    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", token)
    settings = RepoSettings.model_validate(
        shared_endpoint_settings_dict(endpoint=endpoint, token=token)
    )
    ensure_real_tracer_provider()
    return sink_factory(settings.tracing)


@pytest.fixture
def fake_otel_endpoint() -> str:
    """A loopback URL no test should ever hit — proves there is no live network call."""
    return "http://127.0.0.1:1/canary-no-network"


@pytest.fixture
def free_port() -> int:
    """Find an unused TCP port on the loopback interface.

    Binds an ephemeral socket, reads the assigned port, and closes it; the port
    is "free" at the moment of the call (a small race window is acceptable —
    the test server holds it immediately afterwards).
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def fake_otel_transport(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """Record the bytes the OTLP exporter would have sent — no socket, no network.

    Tests register this fixture and assert on the captured payload. The exporter
    code under test must use an injectable transport (W8.1 — the OTLP
    BatchSpanProcessor accepts a custom ``OTLPExporter``); this fixture is the
    injection point.

    Returns a list (mutable) that the test can read after the run.
    """
    captured: list[bytes] = []

    def _capture(payload: bytes) -> None:
        captured.append(payload)

    monkeypatch.setitem(
        __import__("sys").modules, "__capture__", {"payloads": captured, "send": _capture}
    )
    return captured


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every mergecraft-related env var so precedence tests start from a clean slate."""
    env_keys = [
        "MERGECRAFT_LOGFIRE_TOKEN",
        "MERGECRAFT_OTEL_ENDPOINT",
        "MERGECRAFT_TRACING",
        "MERGECRAFT_TRACING_TO",
        "MERGECRAFT_TRACE_DIR",
        "MERGECRAFT_CONFIG",
        "INPUT_TRACING",
        "INPUT_TRACING_TO",
        "INPUT_LOGFIRE_TOKEN",
        "INPUT_OTEL_ENDPOINT",
        "GITHUB_WORKSPACE",
    ]
    for key in env_keys:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def trace_event_payload() -> dict[str, Any]:
    """Minimal ``TraceEvent`` payload for exporter smoke tests."""
    return {
        "kind": "llm.call",
        "span_id": "exp-1",
        "parent_span_id": None,
        "session_id": "run-export",
        "turn_id": "turn-export",
        "tier": "trusted",
        "ts_start_ns": 1_700_000_000_000_000_000,
        "ts_end_ns": 1_700_000_000_001_000_000,
        "status": "ok",
        "attrs": {"model.id": "anthropic/claude-sonnet"},
    }


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """A scratch directory masquerading as ``GITHUB_WORKSPACE`` for CLI precedence tests."""
    return tmp_path
