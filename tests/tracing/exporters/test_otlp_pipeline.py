"""RED contracts for the shared OTLP pipeline (W7.1, W7.3, W7.8).

Issue #56's design point is that ``logfire`` and ``otel`` share a single
implementation: a batched OTLP exporter behind a tracer provider. This module
pins that structural contract end to end and asserts the failure-mode
behaviour (W7.8) the issue requires.
"""

from __future__ import annotations

from typing import Any

import pytest

# ---------------------------------------------------------------------------
# W7.1 — `logfire` and `otel` share one code path (D5).
# ---------------------------------------------------------------------------


def test_logfire_and_otel_share_one_code_path() -> None:
    """Both sink types resolve to the same OTLP-backed exporter class.

    D5 makes this a structural assertion rather than a behavioural one: any
    implementation that ships two parallel code paths is a regression. The
    contract is that ``sink_factory`` returns the *same class* for both
    ``type: logfire`` and ``type: otel`` configuration entries — proving they
    share the underlying exporter.
    """
    pytest.importorskip("logfire")
    pytest.importorskip("opentelemetry")

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import sink_factory

    logfire_settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [
                    {"type": "logfire", "tokenRef": "MERGECRAFT_LOGFIRE_TOKEN", "project": "demo"},
                ],
            }
        }
    ).tracing
    otel_settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [
                    {"type": "otel", "endpoint": "http://127.0.0.1:1/", "headers": {"x-key": "v"}},
                ],
            }
        }
    ).tracing

    logfire_sink = sink_factory(logfire_settings)
    otel_sink = sink_factory(otel_settings)
    assert type(logfire_sink) is type(otel_sink), (
        "logfire and otel must resolve to the same sink class (D5): "
        f"got {type(logfire_sink).__name__} vs {type(otel_sink).__name__}"
    )


def test_logfire_and_otel_share_endpoint_resolution() -> None:
    """Both sinks pass through the same endpoint/headers parser.

    Even when the logfire sink derives its endpoint from ``project`` rather
    than ``endpoint``, the resolved URL ends up at the same exporter. This
    pins the boundary: a fork that re-implements endpoint parsing for one of
    the two sinks is wrong.
    """
    pytest.importorskip("logfire")
    pytest.importorskip("opentelemetry")

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import sink_factory

    logfire_settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "logfire", "tokenRef": "MERGECRAFT_LOGFIRE_TOKEN"}],
            }
        }
    ).tracing
    otel_settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [
                    {
                        "type": "otel",
                        "endpoint": "https://collector.example.internal:4318/v1/traces",
                        "headers": {"x-source": "mergecraft"},
                    }
                ],
            }
        }
    ).tracing
    sink_factory(logfire_settings)
    sink_factory(otel_settings)
    # Structural: the resolver returned sinks sharing a module path — the OTLP
    # pipeline. They are not two unrelated implementations.
    from mergecraft.tracing import exporters  # type: ignore[attr-defined]

    logfire_module = type(sink_factory(logfire_settings)).__module__
    otel_module = type(sink_factory(otel_settings)).__module__
    assert logfire_module == otel_module
    assert logfire_module.startswith("mergecraft.tracing.exporters"), (
        f"expected shared OTLP exporter module path, got {logfire_module}"
    )
    # `exporters` is intentionally re-exported so mypy does not flag an unused import.
    _ = exporters


# ---------------------------------------------------------------------------
# W7.3 — OTLP exporter sends to arbitrary endpoint + headers.
# ---------------------------------------------------------------------------


def test_otel_sink_exports_to_arbitrary_endpoint_and_headers(
    trace_event_payload: dict[str, Any],
) -> None:
    """A self-hosted collector by IP receives the span via the configured endpoint.

    Uses a fake transport (convention 8 — no live network call). Asserts the
    endpoint and headers are honoured end to end.
    """
    pytest.importorskip("opentelemetry")

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import TraceEvent, sink_factory

    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [
                    {
                        "type": "otel",
                        "endpoint": "http://127.0.0.1:4318/v1/traces",
                        "headers": {"x-source": "mergecraft", "authorization": "Bearer canary"},
                    }
                ],
            }
        }
    ).tracing
    sink = sink_factory(settings)
    event = TraceEvent.model_validate(trace_event_payload)
    sink.write(event)
    # The OTLP exporter must have been configured with the supplied endpoint
    # and headers; the fake transport captures the bytes the batch processor
    # flushed. This contract is asserted via the OTLP exporter's own state
    # exposed through the W8 plumbing.
    from mergecraft.tracing.exporters import last_otel_endpoint, last_otel_headers

    assert last_otel_endpoint() == "http://127.0.0.1:4318/v1/traces"
    assert last_otel_headers() == {
        "x-source": "mergecraft",
        # Authorization headers are still forwarded to OTLP — the OTLP layer is
        # *not* the redaction boundary. The redact-on-fan-out layer (D7) is
        # what protects secrets; the export layer just sends what it got.
        "authorization": "Bearer canary",
    }


def test_otel_sink_uses_default_endpoint_when_unset() -> None:
    """Without an explicit endpoint, the OTLP exporter falls back to the package default."""
    pytest.importorskip("opentelemetry")

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import sink_factory

    settings = RepoSettings.model_validate(
        {"tracing": {"enabled": True, "sinks": [{"type": "otel"}]}}
    ).tracing
    sink_factory(settings)
    from mergecraft.tracing.exporters import last_otel_endpoint

    assert last_otel_endpoint()  # non-empty; the OTLP package's default URL.


# ---------------------------------------------------------------------------
# W7.8 — Remote sink failure never fails the run (convention 6).
# ---------------------------------------------------------------------------


def test_remote_sink_failure_never_fails_the_run(
    trace_event_payload: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """An unreachable endpoint is a warning, not a review failure.

    The exporter swallows transport errors (convention 6) — the caller's
    return value is unchanged and a warning is logged at WARNING level.
    """
    pytest.importorskip("opentelemetry")

    import loguru

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import TraceEvent, sink_factory

    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [
                    {
                        "type": "otel",
                        "endpoint": "http://127.0.0.1:1/canary-no-network",
                        "headers": {},
                    }
                ],
            }
        }
    ).tracing
    sink = sink_factory(settings)
    captured: list[str] = []
    sink_id = loguru.logger.add(
        lambda record: captured.append(record.record["message"]), level="WARNING"
    )
    try:
        caller_result = {"review": "unchanged"}
        sink.write(TraceEvent.model_validate(trace_event_payload))
        sink.flush()  # flush so any network attempt happens before assertion
    finally:
        loguru.logger.remove(sink_id)
    assert caller_result == {"review": "unchanged"}
    # A warning was emitted, but the call did not raise.
    assert any("trace" in message.lower() or "otel" in message.lower() for message in captured), (
        f"expected a warning, got: {captured!r}"
    )


def test_remote_sink_flush_is_idempotent_when_unreachable(
    trace_event_payload: dict[str, Any],
) -> None:
    """Calling ``flush`` repeatedly does not surface an exception."""
    pytest.importorskip("opentelemetry")

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import TraceEvent, sink_factory

    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "otel", "endpoint": "http://127.0.0.1:1/"}],
            }
        }
    ).tracing
    sink = sink_factory(settings)
    sink.write(TraceEvent.model_validate(trace_event_payload))
    sink.flush()
    sink.flush()  # second flush must also be a no-op (convention 6)
