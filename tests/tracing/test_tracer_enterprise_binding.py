"""The tracer factory must read a bound enterprise block, never replace it.

``get_tracer_from_settings`` binds ``settings.enterprise`` unconditionally,
including on the disabled path and before it checks for an active span. A
default-constructed caller (``RepoSettings()``) therefore replaces a
trust-bound data-residency allowlist with an empty one — and an empty
allowlist means *unrestricted*. ``docs/TRACING.md`` also guarantees that a
disabled tracer is a no-op, which an enterprise bind is not.

The contract is that the factory never changes a bound block; when unbound it
scopes ``settings.enterprise`` to sink construction (for retention /
``remote_export_allowed``) and resets before returning; and the disabled path
makes no enterprise call at all.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.config import RepoSettings
from mergecraft.enterprise.controls import EnterpriseSettings
from mergecraft.enterprise.runtime import (
    bind_enterprise_from_settings,
    current_enterprise_settings,
    enforce_routed_model_residency,
    reset_enterprise_runtime,
)
from mergecraft.tracing.tracer import NullTracer, Tracer, get_tracer_from_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from _pytest.monkeypatch import MonkeyPatch

_EU_REGIONS = ("eu",)
_US_MODEL = "anthropic/claude-sonnet-5"
_CANARY_ENDPOINT = "http://127.0.0.1:1/canary-enterprise-binding"
_TRACE_ENV_KEYS = (
    "MERGECRAFT_TRACE_ID",
    "MERGECRAFT_TRACE_SESSION_ID",
    "GITHUB_RUN_ID",
    "MERGECRAFT_TRACING",
    "MERGECRAFT_TRACING_TO",
    "MERGECRAFT_OTEL_ENDPOINT",
    "MERGECRAFT_LOGFIRE_TOKEN",
)


def _ensure_real_tracer_provider() -> None:
    pytest.importorskip("opentelemetry")

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    existing = trace.get_tracer_provider()
    if type(existing).__name__ == "ProxyTracerProvider":
        trace.set_tracer_provider(TracerProvider())


def _bind_eu() -> None:
    bind_enterprise_from_settings(EnterpriseSettings(allowed_regions=_EU_REGIONS))


def _assert_eu_binding_holds() -> None:
    """The bound allowlist survives, and still refuses an out-of-region model."""
    assert current_enterprise_settings().allowed_regions == _EU_REGIONS
    with pytest.raises(PermissionError, match="residency"):
        enforce_routed_model_residency(_US_MODEL)


def _disable_tracing(monkeypatch: MonkeyPatch) -> None:
    for key in _TRACE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _enable_tracing(monkeypatch: MonkeyPatch) -> None:
    _disable_tracing(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_TRACING", "true")
    monkeypatch.setenv("MERGECRAFT_OTEL_ENDPOINT", _CANARY_ENDPOINT)


@pytest.fixture(autouse=True)
def _isolate_runtime() -> Iterator[None]:
    from mergecraft.tracing.exporters import _reset_test_seam
    from mergecraft.tracing.sinks import _PENDING_SINK
    from mergecraft.tracing.tracer import reset_process_tracer_cache

    reset_enterprise_runtime()
    reset_process_tracer_cache()
    _PENDING_SINK.set(None)
    _reset_test_seam()
    yield
    reset_enterprise_runtime()
    reset_process_tracer_cache()
    _PENDING_SINK.set(None)
    _reset_test_seam()


def test_disabled_path_leaves_a_bound_enterprise_block_unchanged(
    monkeypatch: MonkeyPatch,
) -> None:
    """Disabled is a no-op — it must not touch enterprise state."""
    _disable_tracing(monkeypatch)
    _bind_eu()

    tracer = get_tracer_from_settings(RepoSettings())

    assert isinstance(tracer, NullTracer)
    _assert_eu_binding_holds()


def test_disabled_path_makes_no_enterprise_call(monkeypatch: MonkeyPatch) -> None:
    """The disabled path must not call the enterprise binder at all."""
    _disable_tracing(monkeypatch)
    runtime = importlib.import_module("mergecraft.enterprise.runtime")
    calls: list[Any] = []

    def _record(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(runtime, "bind_enterprise_from_settings", _record)

    get_tracer_from_settings(RepoSettings())

    assert calls == [], "the disabled path must make no enterprise call"


def test_first_construction_leaves_a_bound_enterprise_block_unchanged(
    monkeypatch: MonkeyPatch,
) -> None:
    """Building the sink must not overwrite a bound allowlist."""
    _ensure_real_tracer_provider()
    _enable_tracing(monkeypatch)
    _bind_eu()

    tracer = get_tracer_from_settings(RepoSettings())

    assert isinstance(tracer, Tracer)
    _assert_eu_binding_holds()


def test_cached_path_leaves_a_bound_enterprise_block_unchanged(
    monkeypatch: MonkeyPatch,
) -> None:
    """The cached-tracer branch returns early; it must not rebind either."""
    _ensure_real_tracer_provider()
    _enable_tracing(monkeypatch)
    settings = RepoSettings()

    first = get_tracer_from_settings(settings)
    assert isinstance(first, Tracer)
    _bind_eu()

    second = get_tracer_from_settings(settings)

    assert second is first
    _assert_eu_binding_holds()


def test_active_span_path_leaves_a_bound_enterprise_block_unchanged(
    monkeypatch: MonkeyPatch,
) -> None:
    """The active-span branch returns the live tracer; the binding must hold."""
    _ensure_real_tracer_provider()
    _enable_tracing(monkeypatch)
    tracer = get_tracer_from_settings(RepoSettings())
    _bind_eu()

    with tracer.start_span("residency-probe"):
        inner = get_tracer_from_settings(RepoSettings())

    assert inner is tracer
    _assert_eu_binding_holds()


def test_unbound_telemetry_off_builds_no_remote_sink_and_stays_unbound(
    monkeypatch: MonkeyPatch,
) -> None:
    """Settings-scoped telemetry must not leak past sink construction."""
    _ensure_real_tracer_provider()
    _disable_tracing(monkeypatch)
    runtime = importlib.import_module("mergecraft.enterprise.runtime")
    exporters = importlib.import_module("mergecraft.tracing.exporters")
    reset_enterprise_runtime()
    assert runtime._BOUND.get() is None

    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "otel", "endpoint": _CANARY_ENDPOINT}],
            },
            "enterprise": {"telemetry": "off"},
        }
    )

    get_tracer_from_settings(settings)

    assert runtime._BOUND.get() is None, (
        "the factory must reset settings.enterprise after sink construction"
    )
    assert runtime.remote_export_allowed() is True, "the unbound default telemetry is restored"
    assert exporters.has_active_tracer_provider() is False, (
        "telemetry: off must not build a remote sink"
    )
