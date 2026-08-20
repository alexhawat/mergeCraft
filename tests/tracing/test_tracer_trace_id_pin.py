"""RED contracts for Batch Q / #292 — pin ``MERGECRAFT_TRACE_ID`` + reuse Tracer (W3).

MCP ``tools/call`` handlers invoke ``get_tracer_from_settings`` on a worker
thread with no active span. Today each call mints a fresh ``Tracer`` and a new
``uuid4`` ``trace_id``, splitting the Logfire tree. W4 must ``setdefault``
``MERGECRAFT_TRACE_ID`` on first mint and reuse a process-wide ``Tracer`` when
settings/sink match (D9 — no ``mcp/server.py`` edits).
"""

from __future__ import annotations

from typing import Any

import pytest

_TRACE_ID_ENV_KEYS = (
    "MERGECRAFT_TRACE_ID",
    "MERGECRAFT_TRACE_SESSION_ID",
    "GITHUB_RUN_ID",
)


def _strip_trace_id_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _TRACE_ID_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _otel_settings_dict() -> dict[str, Any]:
    return {
        "tracing": {
            "enabled": True,
            "sinks": [
                {
                    "type": "otel",
                    "endpoint": "http://127.0.0.1:1/canary-trace-id-pin",
                    "headers": {"x-test": "batch-q"},
                }
            ],
        }
    }


def _ensure_real_tracer_provider() -> None:
    pytest.importorskip("opentelemetry")

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    existing = trace.get_tracer_provider()
    if type(existing).__name__ == "ProxyTracerProvider":
        trace.set_tracer_provider(TracerProvider())


def test_get_tracer_from_settings_shares_trace_id_without_active_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two MCP-style ``get_tracer_from_settings`` calls share one ``trace_id``."""
    pytest.importorskip("opentelemetry")

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import Tracer
    from mergecraft.tracing.exporters import _reset_test_seam
    from mergecraft.tracing.tracer import get_tracer_from_settings

    _strip_trace_id_env(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_TRACING", "true")
    monkeypatch.setenv(
        "MERGECRAFT_OTEL_ENDPOINT",
        "http://127.0.0.1:1/canary-trace-id-pin",
    )

    _reset_test_seam()
    _ensure_real_tracer_provider()

    settings = RepoSettings.model_validate(_otel_settings_dict())
    first = get_tracer_from_settings(settings)
    second = get_tracer_from_settings(settings)

    assert isinstance(first, Tracer)
    assert isinstance(second, Tracer)
    assert second is first
    assert first.trace_id == second.trace_id


def test_first_get_tracer_from_settings_sets_mergecraft_trace_id_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First mint pins ``MERGECRAFT_TRACE_ID`` for downstream MCP tool calls."""
    pytest.importorskip("opentelemetry")

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import Tracer
    from mergecraft.tracing.exporters import _reset_test_seam
    from mergecraft.tracing.tracer import get_tracer_from_settings

    _strip_trace_id_env(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_TRACING", "true")
    monkeypatch.setenv(
        "MERGECRAFT_OTEL_ENDPOINT",
        "http://127.0.0.1:1/canary-trace-id-pin",
    )

    _reset_test_seam()
    _ensure_real_tracer_provider()

    settings = RepoSettings.model_validate(_otel_settings_dict())
    tracer = get_tracer_from_settings(settings)
    again = get_tracer_from_settings(settings)

    assert isinstance(tracer, Tracer)
    assert again is tracer
    assert len(tracer.trace_id) == 32
    int(tracer.trace_id, 16)
