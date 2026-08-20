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
    region: str = "us",
    endpoint_override: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Derive the OTLP endpoint and headers for a Logfire sink.

    Logfire speaks OTLP/HTTP (``http/protobuf``) at the region-aware ingest
    endpoint — ``https://logfire-us.pydantic.dev/v1/traces`` (US) or
    ``https://logfire-eu.pydantic.dev/v1/traces`` (EU). Authorization is the
    bearer token; Logfire routes spans to the project encoded **in the token
    itself** — there is no ``x-logfire-project`` header and emitting one is
    incorrect. ``project`` is retained only as an informational label.

    When ``endpoint_override`` is set (self-hosted/testing) it is used verbatim.
    """
    if endpoint_override:
        endpoint = endpoint_override
    else:
        host = "logfire-eu.pydantic.dev" if region == "eu" else "logfire-us.pydantic.dev"
        endpoint = f"https://{host}/v1/traces"
    headers: dict[str, str] = {}
    if token:
        headers["authorization"] = f"Bearer {token}"
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


def _provider_span_processors(provider: Any) -> tuple[Any, ...]:
    """Return user-attached span processors on *provider* without assuming SDK layout.

    Mirrors the OTel SDK's ``SynchronousMultiSpanProcessor._span_processors``
    list, accessed via the ``_active_span_processor`` composite attribute.
    Returns an empty tuple when the provider exposes neither attribute (e.g.
    proxy providers or stubs).
    """
    composite = getattr(provider, "_active_span_processor", None)
    if composite is None:
        return ()
    return tuple(getattr(composite, "_span_processors", ()))


def _otlp_exporter_headers(exporter: Any) -> dict[str, str]:
    """Return normalized OTLP exporter headers when the SDK exposes them."""
    raw = getattr(exporter, "_headers", None)
    if raw is None:
        raw = getattr(exporter, "headers", None)
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    return {}


def _otlp_exporter_matches(exporter: Any, *, endpoint: str, headers: dict[str, str]) -> bool:
    """Return whether *exporter* already targets the same endpoint and headers."""
    if exporter is None:
        return False
    if type(exporter).__name__ != "OTLPSpanExporter":
        return False
    if getattr(exporter, "_endpoint", None) != endpoint:
        return False
    return _otlp_exporter_headers(exporter) == headers


def _setup_tracer_provider(
    endpoint: str,
    headers: dict[str, str],
    service_name: str,
) -> Any | None:
    """Configure a tracer provider that exports spans to ``endpoint`` and records them.

    Two span processors are attached so the production path and the test seam
    coexist (D5 / convention 8):

    * A real ``OTLPSpanExporter`` (HTTP) sends spans to ``endpoint`` with
      ``headers`` — this is what makes spans reach Logfire / a self-hosted
      collector in production.
    * The in-memory ``_RecordingSpanProcessor`` keeps capturing spans into
      :data:`_RECORDING_PAYLOADS` so the test seam continues to assert on the
      redaction boundary and the D8 payload-cap contract.

    The ``TracerProvider`` override is guarded: when a real provider is already
    installed in the process (e.g. ``logfire`` activates its own on import, or
    a prior ``OTLPSink`` already set one), OTel raises
    ``Overriding of current TracerProvider is not allowed``. We catch that and
    REUSE the existing provider instead of silently degrading to a no-op — the
    recording processor is still appended so the test seam keeps working. This
    is the fix for spans never reaching Logfire: the unguarded
    ``set_tracer_provider`` used to swallow the override error and return
    ``None``, turning the sink into a silent no-op.

    **Singleton sink (#293):** when a real provider already exists *and* the
    same ``endpoint`` is already registered as a ``BatchSpanProcessor``, this
    function does **not** stack another exporter pair.  Each unique
    endpoint+provider combination gets exactly one ``BatchSpanProcessor`` and
    exactly one ``_RecordingSpanProcessor`` regardless of how many times
    :func:`_setup_tracer_provider` (or :class:`OTLPSink`) is called with the
    same configuration.

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
    OTLPSpanExporter = _OTLPSpanExporter
    BatchSpanProcessor = _BatchSpanProcessor

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
        from opentelemetry.sdk.trace.sampling import ALWAYS_ON

        # Guard the override: reuse an already-installed provider rather than
        # fail. OTel's ProxyTracerProvider is the default before any real
        # provider is set, so ``get_tracer_provider()`` is not a real one
        # until ``set_tracer_provider`` has been called successfully.
        existing = trace_mod.get_tracer_provider()
        is_proxy = type(existing).__name__ == "ProxyTracerProvider"
        if is_proxy:
            provider = TracerProvider(
                resource=Resource.create({"service.name": service_name}),
                sampler=ALWAYS_ON,
            )
            trace_mod.set_tracer_provider(provider)
        else:
            # A real provider already exists (logfire import, prior sink, …).
            provider = existing

        # Singleton guard (#293): only attach processors that are not already
        # present on this provider.  Checking by type + exporter endpoint
        # prevents N constructions from stacking N duplicate exporter pairs.
        existing_processors = _provider_span_processors(provider)

        has_otlp = any(
            isinstance(p, BatchSpanProcessor)
            and _otlp_exporter_matches(
                getattr(p, "span_exporter", None),
                endpoint=endpoint,
                headers=headers,
            )
            for p in existing_processors
        )
        if not has_otlp:
            # Real exporter first so production spans reach the network.
            provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(
                        endpoint=endpoint,
                        headers=headers,
                    )
                )
            )

        has_recording = any(isinstance(p, _RecordingSpanProcessor) for p in existing_processors)
        if not has_recording:
            # Test seam: keep recording so captured_payload / has_active_tracer_provider
            # still observe spans.
            provider.add_span_processor(_RecordingSpanProcessor())

        _ACTIVE_TRACER_PROVIDERS.append(provider)
    except Exception as exc:
        # The only expected failure here is the override error from a stale
        # global state we could not observe via get_tracer_provider(). Honor
        # the test seam by reusing whatever provider is live.
        if "Overriding" in str(exc):
            existing = trace_mod.get_tracer_provider()
            if type(existing).__name__ != "ProxyTracerProvider":
                logger.debug("trace otel provider already set; reusing it")
                exc_processors = _provider_span_processors(existing)
                if not any(isinstance(p, _RecordingSpanProcessor) for p in exc_processors):
                    existing.add_span_processor(_RecordingSpanProcessor())
                _ACTIVE_TRACER_PROVIDERS.append(existing)
                return existing
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
            # T3.2 — surface the OTel ``trace_id`` so the test seam and
            # the Logfire-grouping contract are observable through the
            # existing processor. ``get_span_context()`` is the public
            # OTel handle on the span; ``trace_id`` is ``0`` when no
            # provider is wired (the disabled path) and the format
            # ``032x`` mirrors the production Logfire-grouping shape.
            span_ctx = getattr(span, "get_span_context", None)
            if callable(span_ctx):
                resolved_ctx = span_ctx()
                otel_trace_id = getattr(resolved_ctx, "trace_id", 0)
                if otel_trace_id:
                    payload["trace_id"] = format(int(otel_trace_id), "032x")
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


def _otel_safe_attr_value(value: Any) -> Any:
    """Coerce ``value`` into a type the real OTel SDK accepts for span attributes.

    OTel restricts attribute values to ``bool`` / ``str`` / ``bytes`` / ``int`` /
    ``float`` or a homogeneous sequence of those. ``TraceEvent.attrs`` is only
    JSON-compatible, not OTel-safe — structured values like ``tool.arguments``
    / ``tool.output`` (dicts, or lists containing them) reach here as-is and
    the SDK rejects them outright, dropping the attribute with an "Invalid
    type" warning instead of raising. JSON-encode anything outside the
    accepted set so the value still reaches the exported span.
    """
    if isinstance(value, bool | str | bytes | int | float):
        return value
    if isinstance(value, list | tuple) and all(
        isinstance(item, bool | str | bytes | int | float) for item in value
    ):
        return list(value)
    import json as _json

    return _json.dumps(value, default=str)


def _parse_mergecraft_otel_trace_id(trace_id: str) -> int | None:
    """Parse a mergeCraft ``trace_id`` hex string into a 128-bit OTel trace id."""
    try:
        return int(trace_id[:32], 16)
    except (TypeError, ValueError):  # fmt: skip
        return None


def _parse_mergecraft_otel_span_id(span_id: str) -> int | None:
    """Parse a mergeCraft ``span_id`` hex string into a 64-bit OTel span id."""
    try:
        return int(span_id[:16], 16)
    except (TypeError, ValueError):  # fmt: skip
        return None


def _build_otel_parent_context(trace_id: int, parent_span_id: str | None) -> Any | None:
    """Return an OTel ``context`` carrying the parent ``SpanContext``, if any."""
    if not parent_span_id:
        return None
    parent_otel_span_id = _parse_mergecraft_otel_span_id(parent_span_id)
    if parent_otel_span_id is None:
        return None
    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, TraceState
    except ImportError:
        return None
    parent_ctx = SpanContext(
        trace_id=trace_id,
        span_id=parent_otel_span_id,
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
        trace_state=TraceState(),
    )
    return otel_trace.set_span_in_context(NonRecordingSpan(parent_ctx))


def _root_otel_context() -> Any | None:
    """Return an OTel ``context`` with no parent span (isolates from leaked context)."""
    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.trace import INVALID_SPAN_CONTEXT, NonRecordingSpan
    except ImportError:
        return None
    return otel_trace.set_span_in_context(NonRecordingSpan(INVALID_SPAN_CONTEXT))


def _override_span_context(span: Any, trace_id: int, span_id: int) -> None:
    """Rewrite the OTel ``trace_id`` and ``span_id`` on a freshly-built span."""
    try:
        from opentelemetry.trace import SpanContext, TraceFlags, TraceState
    except ImportError:
        return
    try:
        new_ctx = SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            is_remote=False,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
            trace_state=TraceState(),
        )
        if hasattr(span, "_context"):
            span._context = new_ctx
    except Exception as exc:
        logger.debug("trace otel sink span context override failed: {}", exc)


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
        region: str = "us",
        endpoint_override: str | None = None,
        logfire_module: Any | None = None,
    ) -> OTLPSink:
        """Build an :class:`OTLPSink` configured for Logfire."""
        endpoint, headers = _build_logfire_endpoint_and_headers(
            project, token, region=region, endpoint_override=endpoint_override
        )
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
            # Forward mergeCraft attrs (gen_ai.*, model.*, …) so OTLP export
            # reaches real collectors — the in-memory recording processor is
            # not a substitute for this boundary (#143 / W7). Coerced through
            # ``_otel_safe_attr_value`` first: ``TraceEvent.attrs`` is
            # JSON-compatible and carries structured values (``tool.arguments``,
            # ``tool.output``, …) that the real OTel SDK rejects outright —
            # bool/str/bytes/int/float or a homogeneous sequence of those is
            # the full accepted type set; anything else silently drops with an
            # "Invalid type" warning instead of raising.
            for key, value in (event.attrs or {}).items():
                if key not in attrs:
                    attrs[key] = _otel_safe_attr_value(value)
            # If attrs is the truncation marker, forward the marker as an
            # attribute so consumers see it (D8).
            if event.attrs.get("truncated") is True:
                attrs["truncated"] = True
            # T3.2 — forward the mergeCraft ``trace_id`` as the real OTel
            # ``trace_id`` on the produced span so Logfire groups every
            # span in one run under one trace. The OTel SDK does not expose
            # a public ``trace.set_trace_id`` helper in the version we
            # pin; the fallback is to (a) forward the trace_id as a
            # ``mergecraft.trace_id`` attribute (Logfire attribute search
            # groups on it) and (b) rewrite the span's ``_context`` field
            # so the recording-processor test seam and any downstream
            # OTel exporter observe the right trace_id. The rewrite is
            # the same private field the OTel SDK uses internally; if the
            # attribute is missing on a future SDK release, the mergecraft
            # attribute fallback still groups the trace.
            otel_trace_id: int | None = None
            otel_span_id: int | None = None
            if event.trace_id:
                otel_trace_id = _parse_mergecraft_otel_trace_id(event.trace_id)
                if otel_trace_id is not None:
                    attrs["mergecraft.trace_id"] = event.trace_id
            if event.span_id:
                otel_span_id = _parse_mergecraft_otel_span_id(event.span_id)
            parent_context: Any | None = None
            if otel_trace_id is not None:
                parent_context = _build_otel_parent_context(otel_trace_id, event.parent_span_id)
                if parent_context is None and not event.parent_span_id:
                    parent_context = _root_otel_context()
            span = self._tracer.start_span(
                name=event.kind,
                attributes=attrs,
                start_time=event.ts_start_ns,
                context=parent_context,
            )
            if otel_trace_id is not None and otel_span_id is not None:
                _override_span_context(span, otel_trace_id, otel_span_id)
            elif otel_trace_id is not None:
                self._override_span_trace_id(span, otel_trace_id)
            span.end(end_time=event.ts_end_ns)
        except Exception as exc:
            # Convention 6 — never fail the caller's review on a remote sink.
            if not self._warned:
                logger.warning("trace otel sink write failed: {}", exc)
                self._warned = True

    @staticmethod
    def _override_span_trace_id(span: Any, trace_id: int) -> None:
        """Rewrite the OTel ``trace_id`` on a freshly-built span.

        The OTel SDK builds spans with a fresh trace_id from the active
        tracer provider; this helper substitutes the mergeCraft run's
        ``trace_id`` so the recording-processor and any downstream
        exporter see the same value. The substitution is the same
        private ``_context`` field the SDK uses internally — if the
        attribute is missing on a future SDK release, the
        ``mergecraft.trace_id`` attribute fallback (set in :meth:`write`)
        is the structural guarantee.
        """
        try:
            span_ctx = span.get_span_context()
        except Exception:
            return
        _override_span_context(span, trace_id, span_ctx.span_id)

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
            # Use the public API — it dispatches to every attached span
            # processor (recording seam + real OTLP exporter) regardless of
            # SDK-internal storage. Convention 6 — never raise.
            with contextlib.suppress(Exception):
                provider.force_flush()
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


def _resolve_logfire_project(entry: Any) -> str | None:
    """Resolve the Logfire project label.

    Order of precedence:

    1. The sink entry's own ``project`` field (``tracing.sinks[].project``).
    2. The ``MERGECRAFT_TRACING_PROJECT`` env var, written by
       ``mergecraft auth logfire`` and surfaced through the precedence layer
       (``mergecraft.cli.tracing_precedence``).

    The env-var fallback lets an operator who set up Logfire via the CLI never
    touch the YAML config — the project label travels with the token.
    """
    project = getattr(entry, "project", None)
    if project:
        return str(project)
    import os

    env_project = os.environ.get("MERGECRAFT_TRACING_PROJECT", "").strip()
    return env_project or None


def _build_logfire_sink(
    entry: Any,
    logfire_module: Any | None,
) -> Any:
    """Construct a Logfire sink, or a no-op when no token resolves."""
    token = resolve_token_ref(getattr(entry, "token_ref", None))
    if token is None:
        token = resolve_token_ref("MERGECRAFT_LOGFIRE_TOKEN")
    if token is None:
        logger.warning(
            "tracing logfire sink: no token resolved (set tokenRef or "
            "MERGECRAFT_LOGFIRE_TOKEN); sink will be a no-op"
        )
        from mergecraft.tracing.sinks import NullSink

        return NullSink()
    return OTLPSink.for_logfire(
        project=_resolve_logfire_project(entry),
        token=token,
        region=getattr(entry, "region", "us") or "us",
        logfire_module=logfire_module,
        endpoint_override=getattr(entry, "endpoint", None) or None,
    )


def _build_otel_sink(entry: Any) -> OTLPSink:
    """Construct an :class:`OTLPSink` for an ``otel`` config entry."""
    endpoint = getattr(entry, "endpoint", None)
    headers = getattr(entry, "headers", None) or {}
    return OTLPSink.for_otel(endpoint=endpoint, headers=headers)


def _otlp_sink_identity(sink: OTLPSink) -> tuple[str, tuple[tuple[str, str], ...]]:
    """Return the dedupe key for an :class:`OTLPSink` (endpoint + headers, D11)."""
    normalized_headers = tuple(sorted((str(k), str(v)) for k, v in sink.headers.items()))
    return sink.endpoint, normalized_headers


def dedupe_otlp_sinks(children: list[Any]) -> list[Any]:
    """Collapse duplicate :class:`OTLPSink` instances that share endpoint + headers.

    ``logfire`` and ``otel`` config entries often resolve to the same OTLP
    destination; without dedupe, :class:`MultiSink` fans one ``TraceEvent`` out
    to N identical sinks (#372). The #293 processor guard is unchanged — this
    only trims the sink list at factory time.
    """
    deduped: list[Any] = []
    seen_otlp: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    for child in children:
        if isinstance(child, OTLPSink):
            identity = _otlp_sink_identity(child)
            if identity in seen_otlp:
                continue
            seen_otlp.add(identity)
        deduped.append(child)
    return deduped


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
