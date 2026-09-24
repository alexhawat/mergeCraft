"""AR8.3(b) — every ``NullSink`` outcome of ``sink_factory`` resets the exporter seam.

Before AR8.1 only the ``enabled=False`` path reset the seam. The
"enabled tracing, but no remote children" path — enterprise ``telemetry: off``
(or opt-out) with a ``logfire``/``otel`` sink — returned ``NullSink`` while
leaving ``_ACTIVE_TRACER_PROVIDERS`` populated by an earlier OTLP construction
in the same worker. ``has_active_tracer_provider()`` then reported ``True`` and
``tests/enterprise/test_runtime_enforcement.py::test_telemetry_off_skips_remote_sinks``
failed by test order (the CI reproduction: ``test_otlp_pipeline.py`` then
``test_runtime_enforcement.py``).

This module pins the invariant **by construction**, not by test order:
construct an OTLP sink, resolve a disabled remote sink, then require the seam to
be clean. It binds and resets enterprise state itself, so it is independent of
``tests/enterprise/conftest.py``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _isolate_enterprise_binding() -> Iterator[None]:
    """Bind nothing; reset the enterprise ContextVar around each case."""
    from mergecraft.enterprise.runtime import reset_enterprise_runtime

    reset_enterprise_runtime()
    yield
    reset_enterprise_runtime()


def _seed_active_otlp_provider() -> None:
    """Construct an OTLP sink so the exporter test seam records a provider."""
    from mergecraft.tracing.exporters import OTLPSink

    sink = OTLPSink(
        endpoint="http://127.0.0.1:1/ar8-seam-seed",
        headers={},
        service_name="mergecraft-ar8-seam",
    )
    sink._ensure_provider()


@pytest.mark.parametrize("sink_type", ["logfire", "otel"])
def test_null_sink_for_telemetry_off_clears_a_prior_otlp_provider(sink_type: str) -> None:
    """The disabled remote path must reset the seam, not rely on test order."""
    pytest.importorskip("opentelemetry")

    from mergecraft.config import RepoSettings
    from mergecraft.enterprise.controls import EnterpriseSettings
    from mergecraft.enterprise.runtime import bind_enterprise_from_settings
    from mergecraft.tracing.exporters import _reset_test_seam, has_active_tracer_provider
    from mergecraft.tracing.sinks import NullSink, sink_factory

    # (1) A prior OTLP construction in this process populates the seam.
    _reset_test_seam()
    _seed_active_otlp_provider()
    assert has_active_tracer_provider(), "precondition: the OTLP construction records a provider"

    # (2) Enabled tracing with a remote sink, but enterprise telemetry off.
    bind_enterprise_from_settings(EnterpriseSettings(telemetry="off"))
    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [
                    {"type": sink_type, "endpoint": "http://127.0.0.1:1/ar8-disabled"},
                ],
            }
        }
    ).tracing
    resolved = sink_factory(settings)
    assert isinstance(resolved, NullSink), (
        f"telemetry off must resolve to NullSink, got {type(resolved).__name__}"
    )

    # (3) The NullSink outcome itself must clean the seam.
    assert has_active_tracer_provider() is False, (
        "a NullSink outcome must reset the exporter seam even when an earlier "
        "OTLP construction in the same worker populated it"
    )


def test_disabled_tracing_still_clears_a_prior_otlp_provider() -> None:
    """The ``enabled=False`` path keeps resetting the seam after the AR8.1 refactor."""
    pytest.importorskip("opentelemetry")

    from mergecraft.config import RepoSettings
    from mergecraft.tracing.exporters import _reset_test_seam, has_active_tracer_provider
    from mergecraft.tracing.sinks import NullSink, sink_factory

    _reset_test_seam()
    _seed_active_otlp_provider()
    assert has_active_tracer_provider(), "precondition: the OTLP construction records a provider"

    settings = RepoSettings.model_validate(
        {"tracing": {"enabled": False, "sinks": [{"type": "otel"}]}}
    ).tracing
    resolved = sink_factory(settings)
    assert isinstance(resolved, NullSink)
    assert has_active_tracer_provider() is False
