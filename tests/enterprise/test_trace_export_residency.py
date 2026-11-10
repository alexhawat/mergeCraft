"""A bound residency allow-list constrains remote trace export destinations.

Trace sinks are built through the production :func:`sink_factory`. A ``logfire``
sink exports to its region's ingest host (``us`` by default); an ``otel`` sink has
a known region only when its entry declares one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.config.settings import TracingSettings
from mergecraft.enterprise.controls import EnterpriseSettings
from mergecraft.enterprise.runtime import bind_enterprise_from_settings

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    pytest.importorskip("opentelemetry")
    from mergecraft.tracing.exporters import _reset_test_seam

    for key in ("MERGECRAFT_OTEL_ENDPOINT", "MERGECRAFT_TRACING_REGION", "INPUT_OTEL_ENDPOINT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", "placeholder")
    _reset_test_seam()
    yield
    _reset_test_seam()


def _remote_children(sink_entry: dict[str, Any]) -> list[Any]:
    from mergecraft.tracing.exporters import OTLPSink
    from mergecraft.tracing.sinks import sink_factory

    settings = TracingSettings.model_validate({"enabled": True, "sinks": [sink_entry]})
    sink = sink_factory(settings)
    inner = getattr(sink, "inner", None)
    children = getattr(inner, "sinks", []) if inner is not None else []
    return [child for child in children if isinstance(child, OTLPSink)]


def _bind(allowed: tuple[str, ...]) -> None:
    bind_enterprise_from_settings(EnterpriseSettings(allowed_regions=allowed), apply_network=False)


def test_logfire_default_region_refused_under_eu_allow_list() -> None:
    pytest.importorskip("logfire")
    _bind(("eu",))
    assert _remote_children({"type": "logfire"}) == []


def test_logfire_eu_region_allowed_under_eu_allow_list() -> None:
    pytest.importorskip("logfire")
    _bind(("eu-west-1",))
    children = _remote_children({"type": "logfire", "region": "eu"})
    assert [child.endpoint for child in children] == ["https://logfire-eu.pydantic.dev/v1/traces"]


def test_logfire_endpoint_override_refused_under_allow_list() -> None:
    pytest.importorskip("logfire")
    _bind(("eu",))
    entry = {"type": "logfire", "region": "eu", "endpoint": "https://collector.example.invalid"}
    assert _remote_children(entry) == []


def test_otel_without_declared_region_refused_under_allow_list() -> None:
    _bind(("eu",))
    assert _remote_children({"type": "otel", "endpoint": "https://otel.example.invalid"}) == []


def test_otel_with_declared_allowed_region_exports() -> None:
    _bind(("eu",))
    entry = {"type": "otel", "endpoint": "https://otel.example.invalid", "region": "eu"}
    assert [child.endpoint for child in _remote_children(entry)] == ["https://otel.example.invalid"]


def test_no_allow_list_keeps_default_logfire_region() -> None:
    pytest.importorskip("logfire")
    _bind(())
    children = _remote_children({"type": "logfire"})
    assert [child.endpoint for child in children] == ["https://logfire-us.pydantic.dev/v1/traces"]
