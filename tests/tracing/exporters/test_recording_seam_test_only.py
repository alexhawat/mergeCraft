"""The span recorder and the header copy are test-only, never production.

``tracing/exporters.py`` installs ``_RecordingSpanProcessor`` on the live OTLP
provider and keeps a second copy of the authorization header (bearer token
included) in a module global. The exporter already holds the token; a second
copy has no production reader, and the recorder is a test seam.

The contract: a module switch (default off) gates the recorder, the payload
list is bounded, the header global keeps names but masks sensitive values, and
``_RecordingTransport`` is gone.

This module opts out of the enabling autouse fixture so it asserts the
production default.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_SEAM_ATTR = "_RECORDING_SEAM_ENABLED"
_PAYLOAD_PROBE = 4000


@pytest.fixture
def _enable_recording_seam() -> None:
    """Opt out of the suite's enabling fixture: the seam stays off here."""
    return


class _FakeStatus:
    status_code = 0


class _FakeSpan:
    def __init__(self, index: int) -> None:
        self.attributes = {"index": index}
        self.name = "seam-probe"
        self.kind = "internal"
        self.start_time = index
        self.end_time = index + 1
        self.status = _FakeStatus()

    def get_span_context(self) -> Any:
        return None


def _exporters() -> Any:
    return importlib.import_module("mergecraft.tracing.exporters")


def _proxy_sentinel() -> Any:
    """An object whose type name is the SDK's ``ProxyTracerProvider`` sentinel."""
    return type("ProxyTracerProvider", (), {})()


def _pin_provider(monkeypatch: MonkeyPatch, provider: Any) -> Any:
    """Force ``_setup_tracer_provider`` down one provider branch deterministically."""
    otel_trace = importlib.import_module("opentelemetry.trace")
    monkeypatch.setattr(otel_trace, "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(otel_trace, "set_tracer_provider", lambda _provider: None)
    return otel_trace


def _spy_recording_processor(monkeypatch: MonkeyPatch) -> list[str]:
    exporters = _exporters()
    created: list[str] = []

    class _Spy:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            created.append("created")

        def on_start(self, _span: Any, _parent_context: Any = None) -> None:
            return

        def on_end(self, _span: Any) -> None:
            return

        def shutdown(self) -> None:
            return

        def force_flush(self, _timeout_millis: int = 30_000) -> bool:
            return True

    monkeypatch.setattr(exporters, "_RecordingSpanProcessor", _Spy)
    return created


def test_seam_off_adds_no_recording_processor_to_a_new_provider(
    monkeypatch: MonkeyPatch,
) -> None:
    """The fresh-provider branch must not attach the test recorder."""
    pytest.importorskip("opentelemetry")

    from opentelemetry.sdk.trace import TracerProvider

    exporters = _exporters()
    created = _spy_recording_processor(monkeypatch)
    _pin_provider(monkeypatch, _proxy_sentinel())

    provider = exporters._setup_tracer_provider(
        endpoint="http://127.0.0.1:1/canary-seam-new-provider",
        headers={"x-test": "seam-off"},
        service_name="mergecraft-seam-off",
    )

    assert isinstance(provider, TracerProvider)
    assert created == [], "the recorder is a test seam; it must be off by default"


def test_seam_off_adds_no_recording_processor_to_an_existing_provider(
    monkeypatch: MonkeyPatch,
) -> None:
    """The reuse-provider branch must not attach the test recorder either."""
    pytest.importorskip("opentelemetry")

    from opentelemetry.sdk.trace import TracerProvider

    exporters = _exporters()
    created = _spy_recording_processor(monkeypatch)
    existing = TracerProvider()
    _pin_provider(monkeypatch, existing)

    provider = exporters._setup_tracer_provider(
        endpoint="http://127.0.0.1:1/canary-seam-existing-provider",
        headers={"x-test": "seam-off"},
        service_name="mergecraft-seam-off",
    )

    assert provider is existing
    assert created == [], "the recorder is a test seam; it must be off by default"


def test_header_seam_masks_sensitive_values_and_keeps_names() -> None:
    """The global is a reader for tests, not a second copy of the token."""
    exporters = _exporters()
    exporters.OTLPSink(
        endpoint="http://127.0.0.1:1/canary-header-mask",
        headers={"x-source": "mergecraft", "authorization": "Bearer super-secret"},
        service_name="mergecraft-header-mask",
    )

    headers = exporters.last_otel_headers()

    assert headers.get("x-source") == "mergecraft"
    assert "authorization" in headers, "the sensitive key name must stay visible"
    assert "super-secret" not in headers["authorization"], (
        f"the module global must mask sensitive values, got {headers['authorization']!r}"
    )


def test_exporter_still_holds_the_real_authorization_header(monkeypatch: MonkeyPatch) -> None:
    """Masking the global must not touch what the exporter is configured with."""
    pytest.importorskip("opentelemetry")

    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    exporters = _exporters()
    _pin_provider(monkeypatch, _proxy_sentinel())

    provider = exporters._setup_tracer_provider(
        endpoint="http://127.0.0.1:1/canary-exporter-header",
        headers={"authorization": "Bearer real-token", "x-source": "mergecraft"},
        service_name="mergecraft-exporter-header",
    )
    assert provider is not None

    exporter_headers: list[dict[str, str]] = []
    for processor in exporters._provider_span_processors(provider):
        if not isinstance(processor, BatchSpanProcessor):
            continue
        exporter_headers.append(exporters._otlp_exporter_headers(processor.span_exporter))

    assert exporter_headers, "the OTLP exporter must be attached"
    assert any(
        headers.get("authorization") == "Bearer real-token" for headers in exporter_headers
    ), "the live exporter is the token's reader; it must receive the real value"


def test_recording_payload_list_is_bounded() -> None:
    """An unbounded list trades one leak for a memory leak."""
    exporters = _exporters()
    exporters._reset_test_seam()
    processor = exporters._RecordingSpanProcessor()

    for index in range(_PAYLOAD_PROBE):
        processor.on_end(_FakeSpan(index))

    recorded = exporters.captured_payload()
    assert 0 < len(recorded) < _PAYLOAD_PROBE, (
        f"the recording payload list must be bounded; got {len(recorded)} for "
        f"{_PAYLOAD_PROBE} spans"
    )


def test_recording_transport_is_deleted() -> None:
    """The no-op transport had no constructor callers; the class is gone."""
    assert not hasattr(_exporters(), "_RecordingTransport")
