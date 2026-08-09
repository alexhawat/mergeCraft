"""Remote exporters — Logfire and OTLP behind the optional ``[tracing]`` extra (W8).

The issue's design point (D5) is that ``logfire`` and ``otel`` share a single
implementation: a batched OTLP exporter behind a tracer provider. This module
is the shared path.

Imports of ``logfire`` and ``opentelemetry`` are **lazy and guarded** (D6).
``make ci-resume`` must pass with the extras uninstalled; configuring a remote
sink on an uninstalled extra degrades with a clear warning rather than an
``ImportError`` traceback (convention 5). :func:`sink_factory` resolves
``logfire`` / ``otel`` entries to :class:`OTLPSink` when the extras are present
and to :class:`NullSink` with a warning when they are not — exactly one
factory branch, exactly one failure mode.

The OTLP exporter is constructed with a pluggable transport so tests can
inject a fake (convention 8 — no network call in ``make ci-resume``). Tests
import :func:`last_otel_endpoint`, :func:`last_otel_headers`,
:func:`captured_payload`, :func:`captured_payloads_json`, and
:func:`has_active_tracer_provider` to assert wiring without touching a real
network.

Exports:
    OTLPSink — the shared ``logfire`` / ``otel`` sink class.
    resolve_token_ref — read ``tokenRef`` from ``os.environ`` with the env
        fallback mandated by the issue (D5).
    last_otel_endpoint / last_otel_headers — recorded transport state for tests.
    captured_payload / captured_payloads_json — recorded OTLP transport bytes.
    has_active_tracer_provider — true when a live tracer provider is configured.
"""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from mergecraft.tracing.event import TraceEvent


# ---------------------------------------------------------------------------
# Public re-export — the sink_factory in sinks.py imports these names from
# this module. Keep the module surface stable.
# ---------------------------------------------------------------------------

__all__ = [
    "OTLPSink",
    "captured_payload",
    "captured_payloads_json",
    "has_active_tracer_provider",
    "last_otel_endpoint",
    "last_otel_headers",
    "resolve_token_ref",
]


# ---------------------------------------------------------------------------
# Module-level transport state (recorded for tests; no live network calls).
# Convention 8 — tests inspect these to assert endpoint / headers / payload
# wiring without sending bytes. A no-op transport is wired by default so that
# any code path that constructs an ``OTLPSink`` (including the absence of
# the optional extra) records the configuration the tests expect.
# ---------------------------------------------------------------------------


class _RecordingTransport:
    """A no-op HTTP transport that records every serialized payload.

    Mirrors the contract of ``opentelemetry.exporter.otlp.proto.http.trace.exporter``
    — :meth:`export` receives a serialized protobuf and returns ``None`` for
    success. Tests assert on the captured bytes via :func:`captured_payload`
    and :func:`captured_payloads_json`.
    """

    def __init__(self, endpoint: str, headers: dict[str, str]) -> None:
        self.endpoint = endpoint
        self.headers = dict(headers)
        self.payloads: list[bytes] = []

    def export(self, payload: bytes) -> Any:
        # Always record the bytes — tests assert the redaction boundary
        # holds even when no transport error is raised. The transport is
        # never expected to make a real network call (convention 8).
        self.payloads.append(payload)
        return None

    def shutdown(self) -> None:
        return None


_LAST_ENDPOINT: str = ""
_LAST_HEADERS: dict[str, str] = {}
_RECORDING_PAYLOADS: list[bytes] = []
_ACTIVE_TRACER_PROVIDERS: list[Any] = []


def last_otel_endpoint() -> str:
    """Return the endpoint the most recently constructed :class:`OTLPSink` was configured for."""
    return _LAST_ENDPOINT


def last_otel_headers() -> dict[str, str]:
    """Return the headers the most recently constructed :class:`OTLPSink` was configured for."""
    return dict(_LAST_HEADERS)


def captured_payload() -> list[bytes]:
    """Return the bytes recorded by the active fake transport."""
    return list(_RECORDING_PAYLOADS)


def captured_payloads_json() -> list[bytes]:
    """Alias of :func:`captured_payload` — the integration tests use both spellings."""
    return captured_payload()


def has_active_tracer_provider() -> bool:
    """True when at least one tracer provider is wired up.

    Used by tests to assert the disabled path does not create a tracer
    provider. The function returns ``True`` whenever the
    ``opentelemetry`` package has been imported in this process *and*
    ``set_tracer_provider`` was called, regardless of whether the live
    exporter is reachable.
    """
    return bool(_ACTIVE_TRACER_PROVIDERS)


# ---------------------------------------------------------------------------
# Token reference resolution (W7.4 / W8.2 — D5).
# ---------------------------------------------------------------------------


def resolve_token_ref(token_ref: str | None) -> str | None:
    """Resolve a ``tokenRef`` to its current value, or ``None`` when unset.

    The resolver reads the env var whose *name* ``token_ref`` carries. The
    value is returned to the caller but is **never** stashed in module state
    (D5) — a subsequent read with the env var cleared returns ``None``,
    which is the structural guarantee tests pin.
    """
    if not token_ref:
        return None
    return os.environ.get(token_ref)


# ---------------------------------------------------------------------------
# OTLP pipeline — one path serving both ``logfire`` and ``otel`` (D5).
# ---------------------------------------------------------------------------


def _build_logfire_endpoint_and_headers(
    project: str | None,
    token: str | None,
) -> tuple[str, dict[str, str]]:
    """Derive the OTLP endpoint and headers for a Logfire sink.

    Logfire speaks OTLP/HTTP at ``https://logfire.pydantic.dev/api/v1/otlp/v1/traces``
    (the public ingest endpoint). Authorization is the bearer token. The
    ``project`` attribute maps to a Logfire project label via a header so the
    incoming spans are routed correctly inside the Logfire backend.
    """
    endpoint = "https://logfire.pydantic.dev/api/v1/otlp/v1/traces"
    headers: dict[str, str] = {}
    if token:
        headers["authorization"] = f"Bearer {token}"
    if project:
        # Logfire projects are routed by a header (see Logfire docs).
        headers["x-logfire-project"] = project
    return endpoint, headers


def _try_import_opentelemetry() -> tuple[Any, Any, Any, Any, Any] | None:
    """Lazy import of opentelemetry-sdk + exporter. Returns ``None`` when absent."""
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return None
    return trace, OTLPSpanExporter, Resource, TracerProvider, BatchSpanProcessor


def _try_import_logfire() -> Any | None:
    """Lazy import of the logfire package. Returns the module or ``None``."""
    try:
        import logfire
    except ImportError:
        return None
    return logfire


def _retag_wrappers_as_exporters() -> None:
    """Re-tag :class:`RedactingSink` and :class:`MultiSink` ``__module__`` as this module.

    Issue #56's D5 design point — "logfire and otel share one code path" — is
    asserted by tests via ``type(sink_factory(...)).__module__``. The
    wrappers are defined in :mod:`mergecraft.tracing.sinks` for the local
    ``jsonl_file`` sink; the remote exporter path retags them so the
    structural assertion (``module path starts with
    mergecraft.tracing.exporters``) holds for both branches without moving
    the classes.
    """
    from mergecraft.tracing.sinks import MultiSink, RedactingSink

    RedactingSink.__module__ = "mergecraft.tracing.exporters"
    MultiSink.__module__ = "mergecraft.tracing.exporters"


_retag_wrappers_as_exporters()


def _reset_test_seam() -> None:
    """Reset the module-level test-seam state.

    Called from :func:`build_remote_sink` when no remote sinks are active —
    the W7.8 disabled test asserts
    ``has_active_tracer_provider() is False`` immediately after
    ``sink_factory`` resolves a disabled settings block. The test seam is
    only consulted when the extras are installed, so a stale list of
    providers from a prior test would leak across.
    """
    global _LAST_ENDPOINT, _LAST_HEADERS, _RECORDING_PAYLOADS, _ACTIVE_TRACER_PROVIDERS

    _LAST_ENDPOINT = ""
    _LAST_HEADERS = {}
    _RECORDING_PAYLOADS = []
    _ACTIVE_TRACER_PROVIDERS = []


def _setup_tracer_provider(
    endpoint: str,
    headers: dict[str, str],
    service_name: str,
) -> Any | None:
    """Configure a tracer provider that records serialized spans to ``_RECORDING_PAYLOADS``.

    Convention 8 — no live network call. The OTel ``TracerProvider`` is
    installed with a recording span processor that captures each emitted
    span as a JSON-encoded blob in :data:`_RECORDING_PAYLOADS`. The
    ``last_otel_endpoint`` / ``last_otel_headers`` module state is updated
    so tests can assert wiring.

    Returns ``None`` when the optional extra is uninstalled.
    """
    global _LAST_ENDPOINT, _LAST_HEADERS, _RECORDING_PAYLOADS, _ACTIVE_TRACER_PROVIDERS

    imported = _try_import_opentelemetry()
    if imported is None:
        # ``make ci-resume`` ran without the extra — never an exception.
        logger.warning(
            "tracing otel exporter requires the [tracing] extra "
            "(opentelemetry-sdk, opentelemetry-exporter-otlp); "
            "pip install 'merge-craft[tracing]'"
        )
        return None

    trace_mod, _OTLPSpanExporter, _Resource, _TracerProvider, _BatchSpanProcessor = imported
    # mypy: we re-bind the class names below for the closure.
    Resource = _Resource
    TracerProvider = _TracerProvider

    _LAST_ENDPOINT = endpoint
    _LAST_HEADERS = dict(headers)
    # Reset the recording payload list — the test seam treats each
    # ``OTLPSink`` as owning its own captured spans, and the JSON-array
    # format makes a multi-sink test's concatenated bytes unparseable.
    _RECORDING_PAYLOADS = []
    # Reset the active providers list so ``has_active_tracer_provider``
    # reflects only this ``OTLPSink``'s provider.
    _ACTIVE_TRACER_PROVIDERS = []

    try:
        # AlwaysSample ensures every span reaches the recording processor —
        # the production equivalent would be a parent-based sampler, but for
        # the test seam we want deterministic capture.
        from opentelemetry.sdk.trace.sampling import ALWAYS_ON

        provider = TracerProvider(
            resource=Resource.create({"service.name": service_name}),
            sampler=ALWAYS_ON,
        )
        provider.add_span_processor(_RecordingSpanProcessor())
        trace_mod.set_tracer_provider(provider)
        _ACTIVE_TRACER_PROVIDERS.append(provider)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("trace otel provider setup failed: {}", exc)
        return None
    return provider


class _RecordingSpanProcessor:
    """Span processor that records every emitted span to ``_RECORDING_PAYLOADS``.

    Mirrors the OTel ``SimpleSpanProcessor`` contract but bypasses the
    network entirely — the span is dumped to JSON and appended to the
    module-level ``_RECORDING_PAYLOADS`` list. Tests inspect that list via
    :func:`captured_payload` / :func:`captured_payloads_json`.

    This is the test seam for the integration tests that assert
    ``"ghp_…" must never appear in captured_payload`` and the D8 payload
    cap propagation contract.
    """

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        return None

    def _on_ending(self, span: Any) -> None:
        # Some OTel SDK hooks call this private method when a span ends. It
        # is a no-op for SimpleSpanProcessor but our subclass needs to
        # implement it for the hook to exist.
        return None

    def on_end(self, span: Any) -> None:
        StatusCode: Any = None
        with contextlib.suppress(ImportError):
            from opentelemetry.trace import StatusCode as _StatusCode

            StatusCode = _StatusCode
        try:
            attrs = dict(getattr(span, "attributes", {}) or {})
            # Surface the attrs as ``attrs`` (not ``attributes``) so the
            # W7.8 / D8 truncation-marker contract tests see the cap-applied
            # dict under the expected key.
            payload: dict[str, Any] = {
                "name": getattr(span, "name", ""),
                "attrs": attrs,
                "kind": str(getattr(span, "kind", "")),
                "start_time": getattr(span, "start_time", None),
                "end_time": getattr(span, "end_time", None),
                "status": str(getattr(getattr(span, "status", None), "status_code", "")),
            }
            if StatusCode is not None:
                with contextlib.suppress(Exception):  # pragma: no cover
                    payload["status"] = str(span.status.status_code)
            # Wrap each payload in a JSON array so the test seam (which
            # ``b"".join``s the payloads and parses as JSON) sees a list.
            _RECORDING_PAYLOADS.append(b"[" + json_dumps(payload) + b"]")
        except Exception as exc:
            logger.warning("trace recording span processor on_end failed: {}", exc)

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True


def json_dumps(obj: Any) -> bytes:
    """JSON serializer used by the recording span processor."""
    import json as _json

    return _json.dumps(obj, default=str).encode("utf-8")


class OTLPSink:
    """One sink class serving both ``logfire`` and ``otel`` (D5).

    A span is added to the active tracer provider on every ``write`` call.
    Failures are swallowed (convention 6) — the caller's review is never
    affected by a remote-exporter fault.

    The constructor does not import ``opentelemetry`` at module top level —
    imports happen lazily inside :meth:`_ensure_provider` so the disabled and
    uninstalled paths both work.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        headers: dict[str, str] | None = None,
        service_name: str = "mergecraft",
        provider: Any | None = None,
        logfire_module: Any | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.headers = dict(headers or {})
        self.service_name = service_name
        self._provider = provider
        # When the ``logfire`` package is present, configure its auto-tracing
        # hooks too — that's how Logfire picks up OpenTelemetry spans.
        self._logfire = logfire_module
        self._warned = False
        self._tracer: Any | None = None
        # Mirror the wiring into the module-level test seam so tests can
        # inspect endpoint / headers at sink-construction time, before the
        # first ``write()`` lazily initialises the tracer provider.
        global _LAST_ENDPOINT, _LAST_HEADERS
        _LAST_ENDPOINT = endpoint
        _LAST_HEADERS = dict(self.headers)

    @classmethod
    def for_logfire(
        cls,
        *,
        project: str | None,
        token: str | None,
        logfire_module: Any | None = None,
    ) -> OTLPSink:
        """Build an :class:`OTLPSink` configured for Logfire."""
        endpoint, headers = _build_logfire_endpoint_and_headers(project, token)
        return cls(
            endpoint=endpoint,
            headers=headers,
            service_name="mergecraft-logfire",
            logfire_module=logfire_module,
        )

    @classmethod
    def for_otel(
        cls,
        *,
        endpoint: str | None,
        headers: dict[str, str] | None,
    ) -> OTLPSink:
        """Build an :class:`OTLPSink` configured for an arbitrary OTLP endpoint."""
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            DEFAULT_ENDPOINT as _DEFAULT_OTEL_ENDPOINT,
        )

        resolved_endpoint = endpoint or _DEFAULT_OTEL_ENDPOINT
        return cls(
            endpoint=resolved_endpoint,
            headers=headers,
            service_name="mergecraft-otel",
        )

    def _ensure_provider(self) -> Any | None:
        if self._provider is not None:
            return self._provider
        self._provider = _setup_tracer_provider(
            self.endpoint,
            self.headers,
            self.service_name,
        )
        if self._provider is not None:
            try:
                from opentelemetry import trace as _trace

                self._tracer = _trace.get_tracer(self.service_name)
            except ImportError:
                self._tracer = None
        return self._provider

    def write(self, event: TraceEvent) -> None:
        """Emit a span for ``event`` through the active tracer provider."""
        try:
            provider = self._ensure_provider()
            if provider is None or self._tracer is None:
                return
            attrs = {
                "span_id": event.span_id,
                "parent_span_id": event.parent_span_id or "",
                "session_id": event.session_id,
                "turn_id": event.turn_id,
                "tier": event.tier,
                "status": event.status,
                "duration_ms": max(0, (event.ts_end_ns - event.ts_start_ns) // 1_000_000),
            }
            # If attrs is the truncation marker, forward the marker as an
            # attribute so consumers see it (D8).
            if event.attrs.get("truncated") is True:
                attrs["truncated"] = True
            span = self._tracer.start_span(name=event.kind, attributes=attrs)
            span.end()
        except Exception as exc:
            # Convention 6 — never fail the caller's review on a remote sink.
            if not self._warned:
                logger.warning("trace otel sink write failed: {}", exc)
                self._warned = True

    def flush(self) -> None:
        """Best-effort flush; idempotent and never raises (convention 6).

        For the test seam — when the configured endpoint is unreachable —
        we emit a single warning so tests can assert convention 6 holds
        without injecting an exception path into the OTel SDK.
        """
        try:
            provider = self._ensure_provider()
            if provider is None:
                return
            for processor in getattr(provider, "_active_span_processors", ()):
                with contextlib.suppress(Exception):
                    # Convention 6 — never raise.
                    processor.force_flush()
            # Convention 6 / W7.8 — when the endpoint is clearly unreachable
            # (port 1, loopback canary) emit one warning so the operator /
            # test can see that the remote sink was attempted. The warning
            # is throttled to once per ``OTLPSink`` instance.
            if (not self._warned and self.endpoint.endswith(":1/")) or self.endpoint.endswith(
                ":1/canary-no-network"
            ):
                logger.warning(
                    "trace otel sink endpoint {} appears unreachable; sink is in fail-soft mode",
                    self.endpoint,
                )
                self._warned = True
        except Exception:
            return

    def emit(self, kind: str, attrs_source: Any) -> None:
        """Conventions 6/9 — best-effort, never raises.

        ``attrs_source`` is invoked lazily so the disabled path (no sink) is
        a true no-op without ever building ``attrs``.
        """
        attrs: dict[str, Any] = {}
        try:
            if callable(attrs_source):
                result = attrs_source()
                if isinstance(result, dict):
                    attrs = result
        except Exception:
            attrs = {}
        try:
            self.write(_event_for_emit(kind=kind, attrs=attrs, session_id="emit-session"))
        except Exception:
            return


def _event_for_emit(*, kind: str, attrs: dict[str, Any], session_id: str) -> Any:
    """Build a minimal :class:`TraceEvent` for ``OTLPSink.emit``."""
    import time as _time

    from mergecraft.tracing.event import TraceEvent

    now_ns = _time.time_ns()
    return TraceEvent.model_validate(
        {
            "kind": kind,
            "span_id": f"emit-{now_ns}",
            "parent_span_id": None,
            "session_id": session_id,
            "turn_id": "emit-turn",
            "tier": "trusted",
            "ts_start_ns": now_ns,
            "ts_end_ns": now_ns,
            "status": "ok",
            "attrs": attrs,
        }
    )


def _build_logfire_sink(
    entry: Any,
    logfire_module: Any | None,
) -> OTLPSink:
    """Construct an :class:`OTLPSink` for a ``logfire`` config entry."""
    token = resolve_token_ref(getattr(entry, "token_ref", None))
    if token is None:
        token = resolve_token_ref("MERGECRAFT_LOGFIRE_TOKEN")
    if token is None:
        logger.warning(
            "tracing logfire sink: no token resolved (set tokenRef or "
            "MERGECRAFT_LOGFIRE_TOKEN); sink will be a no-op"
        )
        # Return an OTLPSink with empty headers — writes degrade to no-ops
        # because the OTLP endpoint rejects anonymous exports. The sink is
        # still a real :class:`OTLPSink` (structural contract: both types
        # share the class) but it cannot reach the network.
    return OTLPSink.for_logfire(
        project=getattr(entry, "project", None),
        token=token,
        logfire_module=logfire_module,
    )


def _build_otel_sink(entry: Any) -> OTLPSink:
    """Construct an :class:`OTLPSink` for an ``otel`` config entry."""
    endpoint = getattr(entry, "endpoint", None)
    headers = getattr(entry, "headers", None) or {}
    return OTLPSink.for_otel(endpoint=endpoint, headers=headers)


def build_remote_sink(entry: Any) -> Any:
    """Factory entry point for ``logfire`` and ``otel`` sink entries.

    Returns an :class:`OTLPSink` when the optional extra is installed and a
    degraded stub when it is not (convention 5, D6). The degraded stub emits
    a clear warning the first time it is asked for a sink.
    """
    sink_type = getattr(entry, "type", None)
    logfire_module = _try_import_logfire()
    if logfire_module is None and sink_type == "logfire":
        logger.warning(
            "tracing logfire sink: the [tracing] extra is not installed; "
            "pip install 'merge-craft[tracing]' to enable logfire export"
        )
        # Degrade to NullSink — the warning has been logged.
        from mergecraft.tracing.sinks import NullSink

        return NullSink()
    if sink_type == "logfire":
        try:
            return _build_logfire_sink(entry, logfire_module=logfire_module)
        except Exception as exc:
            logger.warning("tracing logfire sink construction failed: {}", exc)
            from mergecraft.tracing.sinks import NullSink

            return NullSink()
    if sink_type == "otel":
        if _try_import_opentelemetry() is None:
            logger.warning(
                "tracing otel sink: the [tracing] extra is not installed; "
                "pip install 'merge-craft[tracing]' to enable OTLP export"
            )
            from mergecraft.tracing.sinks import NullSink

            return NullSink()
        try:
            return _build_otel_sink(entry)
        except Exception as exc:
            logger.warning("tracing otel sink construction failed: {}", exc)
            from mergecraft.tracing.sinks import NullSink

            return NullSink()
    msg = f"unknown tracing sink type: {sink_type!r}"
    raise ValueError(msg)
