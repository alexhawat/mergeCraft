"""Repeated tracer lookups share identity without pinning generated IDs in the environment.

Run lifecycle owners request a fresh tracer; detached helpers within the run
reuse its identity. Generated IDs must not leak into later review lifecycles.
"""

from __future__ import annotations

import os
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


def test_first_get_tracer_from_settings_keeps_generated_trace_id_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cached helper lookups reuse identity without changing process environment."""
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
    assert "MERGECRAFT_TRACE_ID" not in os.environ
