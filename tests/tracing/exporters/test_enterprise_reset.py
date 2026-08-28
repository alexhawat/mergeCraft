"""DQ1 RED — enterprise reset path in ``reset_process_tracer_cache`` (#509, DQ7)."""

from __future__ import annotations

import pytest

from mergecraft.config import RepoSettings
from mergecraft.enterprise.controls import EnterpriseSettings
from mergecraft.enterprise.runtime import bind_enterprise_from_settings
from mergecraft.tracing.exporters import OTLPSink
from mergecraft.tracing.sinks import _PENDING_SINK, claim_sink, sink_factory
from mergecraft.tracing.tracer import reset_process_tracer_cache


def test_reset_process_tracer_cache_clears_the_enterprise_path() -> None:
    """Leaked enterprise opt-out must be cleared so OTLP ``claim_sink`` succeeds."""
    pytest.importorskip("opentelemetry")

    bind_enterprise_from_settings(EnterpriseSettings(telemetry="off"))
    memory_settings = RepoSettings.model_validate(
        {"tracing": {"enabled": True, "sinks": [{"type": "memory"}]}}
    ).tracing
    sink_factory(memory_settings)
    assert _PENDING_SINK.get() is not None

    reset_process_tracer_cache()

    otel_settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [
                    {
                        "type": "otel",
                        "endpoint": "http://127.0.0.1:1/canary-enterprise-reset",
                        "headers": {},
                    }
                ],
            }
        }
    ).tracing
    claimed = claim_sink(otel_settings)
    child = claimed.inner.sinks[0]
    assert isinstance(child, OTLPSink), (
        f"expected OTLPSink after enterprise reset, got {type(child).__name__}"
    )


def test_reset_is_idempotent() -> None:
    """Repeated resets must not break subsequent enterprise/runtime state."""
    pytest.importorskip("opentelemetry")

    bind_enterprise_from_settings(EnterpriseSettings(telemetry="off"))
    reset_process_tracer_cache()
    reset_process_tracer_cache()

    otel_settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [
                    {
                        "type": "otel",
                        "endpoint": "http://127.0.0.1:1/canary-enterprise-reset-idempotent",
                        "headers": {},
                    }
                ],
            }
        }
    ).tracing
    claimed = claim_sink(otel_settings)
    child = claimed.inner.sinks[0]
    assert isinstance(child, OTLPSink)
