"""Outbound HTTP instrumentation — emit one http.client.request span per send.

A mergeCraft-instrumented httpx client emits one OTel-shaped span per
``send()`` call with the request URL (redacted inline), method, status
code, and duration. The span nests under the currently-active
mergeCraft Span via the OTel context bridge (see otel_bridge.py), so
every outbound HTTP row in Logfire sits under the same trace_id as the
LLM/tool span that triggered it.

Exports:
    instrument_httpx — wrap an httpx.Client or AsyncClient so every send
        emits one span. Idempotent.
    HttpRequestSpanContext — internal context manager emitted per send.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.tracing.redaction import redact_url

if TYPE_CHECKING:
    from mergecraft.tracing.tracer import Span, Tracer

_INSTRUMENTED_SENTINEL = "_mergecraft_instrumented"
_HTTP_SPAN_KIND = "http.client.request"


def _resolve_tracer(tracer: Tracer | None) -> Tracer | None:
    """Return the tracer to emit under, or ``None`` if tracing is disabled.

    Convention 9 / #56 D9 — the disabled path is a true no-op. Any wrapper
    that resolves ``NullTracer`` short-circuits to ``None`` so the
    instrumented httpx client's :meth:`send` runs unwrapped.

    The review audit flagged a NullTracer asymmetry (Low 2 / W4 H6): a caller
    passing ``tracer=None`` falls into the lazy ``get_tracer_from_settings``
    branch which is silent on the no-op path. The fix treats both
    ``None`` (caller passed None directly) and ``NullTracer`` (the disabled
    surface ``get_tracer_from_settings`` returns) as the no-op sentinel —
    the function returns ``None`` for either shape — and emits a single
    ``debug`` log line when the resolver returns ``None`` so the silent loss
    is no longer silent. The instrumented client does not raise; the
    ``test_disabled_tracer_path_emits_no_http_span`` contract pins the
    no-op behavior.
    """
    if tracer is not None:
        return tracer
    try:
        from mergecraft.config import RepoSettings
        from mergecraft.tracing.tracer import (
            NullTracer,
            get_tracer_from_settings,
        )

        resolved = get_tracer_from_settings(RepoSettings())
    except Exception as exc:
        logger.debug("instrument_httpx tracer resolution failed: {}", exc)
        return None
    if resolved is None or isinstance(resolved, NullTracer):
        logger.debug(
            "instrument_httpx resolving to no-op tracer (NullTracer or None); "
            "http spans will not be emitted until a Tracer is wired"
        )
        return None
    return resolved


def _http_attr_payload(
    *,
    method: str,
    url: str,
    duration_ms: int,
    status_code: int,
    request_bytes: int,
    response_bytes: int,
    error_class: str | None = None,
) -> dict[str, Any]:
    """Build the ``http.client.request`` span attrs dict."""
    attrs: dict[str, Any] = {
        "http.method": method,
        "http.url": url,
        "http.status_code": status_code,
        "http.duration_ms": duration_ms,
        "http.request_bytes": request_bytes,
        "http.response_bytes": response_bytes,
    }
    if error_class:
        attrs["http.error_class"] = error_class
    return attrs


def _safe_request_bytes(request: Any) -> int:
    """Return ``len(request.content)`` when it is bytes-like, else 0."""
    content = getattr(request, "content", None)
    if isinstance(content, (bytes, bytearray, memoryview)):
        return len(content)
    return 0


def _safe_response_bytes(response: Any) -> int:
    """Return ``len(response.content)`` when available, else 0."""
    content = getattr(response, "content", None)
    if isinstance(content, (bytes, bytearray, memoryview)):
        return len(content)
    return 0


def _open_http_span(tracer: Tracer, *, parent_span_id: str | None) -> Span | None:
    """Open one ``http.client.request`` span, parented to the active span.

    The parent defaults to whichever mergeCraft span is currently active
    (typically the in-flight ``llm.call`` / ``provider.call``). The
    returned span is entered in the caller.
    """
    return tracer.start_span(_HTTP_SPAN_KIND, parent_span_id=parent_span_id)


def _close_http_span(
    span: Span,
    *,
    method: str,
    request: Any,
    response: Any,
    duration_ns: int,
    error: BaseException | None,
) -> None:
    """Stamp the ``http.client.request`` span attrs and close it.

    On exception: the span is closed with ``status="error"`` and the
    ``http.error_class`` attribute set to ``type(exc).__name__``. The
    span always emits — even on failure (T2.1 test 10). The exception
    itself is re-raised by the wrapper after the span closes, so the
    caller's ``with pytest.raises(...)`` keeps working.
    """
    duration_ms = max(0, duration_ns // 1_000_000)
    url = redact_url(str(getattr(request, "url", "") or ""))
    if error is None:
        status_code = int(getattr(response, "status_code", 0) or 0)
        attrs = _http_attr_payload(
            method=str(method),
            url=url,
            duration_ms=duration_ms,
            status_code=status_code,
            request_bytes=_safe_request_bytes(request),
            response_bytes=_safe_response_bytes(response),
        )
    else:
        attrs = _http_attr_payload(
            method=str(method),
            url=url,
            duration_ms=duration_ms,
            status_code=0,
            request_bytes=_safe_request_bytes(request),
            response_bytes=0,
            error_class=type(error).__name__,
        )
        span.record_exception(error)
    for key, value in attrs.items():
        span.set_attribute(key, value)
    span.close()


def _wrap_sync_send(client: Any, tracer: Tracer) -> None:
    """Replace ``Client.send`` with a tracing wrapper (idempotent)."""
    # ``Client.send`` is a bound method on the instance; capture it before
    # overwriting so we still have a reference to the original callable.
    original_send = client.send

    def send(request: Any, *args: Any, **kwargs: Any) -> Any:
        active = client._mergecraft_active_span()
        parent_id: str | None = getattr(active, "span_id", None) if active is not None else None
        span = _open_http_span(tracer, parent_span_id=parent_id)
        if span is None:
            return original_send(request, *args, **kwargs)
        span.__enter__()
        method = str(getattr(request, "method", "GET"))
        started = time.time_ns()
        try:
            response = original_send(request, *args, **kwargs)
        except BaseException as exc:
            _close_http_span(
                span,
                method=method,
                request=request,
                response=None,
                duration_ns=time.time_ns() - started,
                error=exc,
            )
            raise
        _close_http_span(
            span,
            method=method,
            request=request,
            response=response,
            duration_ns=time.time_ns() - started,
            error=None,
        )
        return response

    client.send = send

    def _active() -> Any:
        from mergecraft.tracing.tracer import active_span_for

        return active_span_for(tracer)

    client._mergecraft_active_span = _active


def _wrap_async_send(client: Any, tracer: Tracer) -> None:
    """Replace ``AsyncClient.send`` with an async tracing wrapper (idempotent)."""
    # Same as ``_wrap_sync_send``: ``AsyncClient.send`` is already a bound
    # coroutine function on the instance; capturing it before overwriting
    # preserves the original callable.
    original_send = client.send

    async def send(request: Any, *args: Any, **kwargs: Any) -> Any:
        active = client._mergecraft_active_span()
        parent_id: str | None = getattr(active, "span_id", None) if active is not None else None
        span = _open_http_span(tracer, parent_span_id=parent_id)
        if span is None:
            result: Any = original_send(request, *args, **kwargs)
            return await result
        span.__enter__()
        method = str(getattr(request, "method", "GET"))
        started = time.time_ns()
        try:
            response_coro: Any = original_send(request, *args, **kwargs)
            response = await response_coro
        except BaseException as exc:
            _close_http_span(
                span,
                method=method,
                request=request,
                response=None,
                duration_ns=time.time_ns() - started,
                error=exc,
            )
            raise
        _close_http_span(
            span,
            method=method,
            request=request,
            response=response,
            duration_ns=time.time_ns() - started,
            error=None,
        )
        return response

    client.send = send

    def _active() -> Any:
        from mergecraft.tracing.tracer import active_span_for

        return active_span_for(tracer)

    client._mergecraft_active_span = _active


def _is_async_client(client: Any) -> bool:
    """Return ``True`` when ``client`` is an :class:`httpx.AsyncClient`."""
    cls = type(client)
    return bool(getattr(cls, "__module__", "").startswith("httpx")) and cls.__name__ in {
        "AsyncClient",
    }


def instrument_httpx(client: Any, *, tracer: Any = None) -> None:
    """Wrap ``client.send`` so every send emits a ``http.client.request`` span.

    D8 — narrow instrumentation: only the clients mergeCraft constructs are
    wrapped. No global monkey-patch. Idempotent via the
    ``_mergecraft_instrumented`` sentinel so a caller that re-instruments a
    shared client does not double-wrap.

    Args:
        client: An :class:`httpx.Client` or :class:`httpx.AsyncClient`
            instance. Must already exist at call time so the wrapper can
            install on the exact instance the caller plans to use.
        tracer: Optional :class:`Tracer` to emit under. When ``None`` the
            helper resolves via ``get_tracer_from_settings``; when that
            resolves to a :class:`NullTracer`, the call is a no-op and
            no sentinel is set.

    Examples:
        >>> import httpx
        >>> from mergecraft.tracing import Tracer, MemorySink
        >>> sink = MemorySink()
        >>> tracer = Tracer(sink=sink, session_id="s", run_id="r")
        >>> client = httpx.Client(timeout=5.0)
        >>> instrument_httpx(client, tracer=tracer)
        >>> client.close()
    """
    if client is None:
        return
    if getattr(client, _INSTRUMENTED_SENTINEL, False):
        return

    resolved = _resolve_tracer(tracer)
    if resolved is None:
        # Disabled path: do not install a wrapper, do not set the sentinel —
        # a later ``instrument_httpx(client, tracer=...)`` call can still
        # activate the instrumentation. This matches the T2.1 test 12
        # contract: ``NullTracer`` is a true no-op rather than a sticky
        # "never instrumented" lockout.
        return

    if _is_async_client(client):
        _wrap_async_send(client, resolved)
    else:
        _wrap_sync_send(client, resolved)
    setattr(client, _INSTRUMENTED_SENTINEL, True)


__all__ = ["instrument_httpx"]
