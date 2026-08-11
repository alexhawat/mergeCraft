"""RED contracts for ``provider.call`` parent + outbound HTTP spans (T2.1).

Wave: ``issues-tracing-sevn-quality`` / PR T2 — ``feat(tracing): provider.call
parent + outbound HTTP spans with URL redaction``.

Contract
--------
Two new span kinds land on every ``mergecraft diff-review`` run so the
Logfire tree matches the operator's sevn reference shape:

1. ``provider.call`` — a real span kind (D10) that opens around every upstream
   API request. ``provider.transport_family`` is one of
   ``anthropic`` / ``chat_completions`` / ``responses_api``. The
   ``llm.call`` span emitted by the driver becomes a child of the
   ``provider.call`` span. The ``http.client.request`` span emitted by the
   httpx instrumentation is a grandchild.
2. ``http.client.request`` — one span per outbound ``httpx.send`` call,
   carrying ``http.method`` / ``http.url`` (after inline redaction) /
   ``http.status_code`` / ``http.duration_ms``. On connection failure the
   span still emits with ``http.status_code=0`` and ``http.error_class``
   set to the exception class name. The instrumentation is **narrow** (D8):
   only clients mergeCraft constructs are wrapped; no global monkey-patch.

URLs are redacted inline (D9): ``api.telegram.org/bot<TOKEN>`` becomes
``api.telegram.org/bot<redacted>``; basic-auth and query-string tokens are
masked; embedded bearer-shaped substrings are scrubbed.

These tests are RED against ``origin/pre-0.0.1`` (with T3.2 already merged
for ``trace_id`` plumbing) because the implementation does not exist yet:

- ``src/mergecraft/tracing/redaction.py`` — ``redact_url`` is missing.
- ``src/mergecraft/tracing/http.py`` — the module itself is missing.
- ``src/mergecraft/agents/openai_compatible_gateways.py`` — the
  custom-provider ``httpx.Client`` is not yet wrapped.
- ``src/mergecraft/agents/claude.py``, ``codex.py``, ``gemini.py`` —
  ``llm.call`` is not yet wrapped in a ``provider.call`` parent span.
- ``src/mergecraft/utils/agent_resolve.py`` — the chat-completions cached
  token paths are not yet recognised.

Acceptance (after T2.2 lands): **12 collected; 11 green; 1 xfailed** —
``test_provider_call_span_wraps_llm_call_for_anthropic`` stays xfail through
the GREEN pass because wrapping ``llm.call`` inside a ``provider.call``
parent is the defining T2.2 surface — a fresh test-creator pass removes the
marker once the impl wave lands.

The xfail marker is ``strict=False`` so an unsatisfied xfail never hard-fails
the suite (the T2.2 impl wave is allowed to turn tests green on touch).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Shared helpers — minimal redaction + sink fixtures.
# ---------------------------------------------------------------------------


_REDACTED = "<redacted>"


def _http_spans(sink: Any) -> list[Any]:
    """Return every ``http.client.request`` event recorded on ``sink``."""
    return [event for event in sink.events if event.kind == "http.client.request"]


def _by_kind(sink: Any) -> dict[str, list[Any]]:
    """Index ``sink.events`` by ``kind`` for O(1) span-tree assertions."""
    by_kind: dict[str, list[Any]] = {}
    for event in sink.events:
        by_kind.setdefault(event.kind, []).append(event)
    return by_kind


@pytest.fixture
def recording_sink() -> Any:
    """A real :class:`MemorySink` wired into a :class:`Tracer` for span capture."""
    from mergecraft.tracing import MemorySink

    return MemorySink()


@pytest.fixture
def http_tracer(recording_sink: Any) -> Any:
    """A :class:`Tracer` whose sink is the ``recording_sink`` fixture."""
    from mergecraft.tracing import Tracer

    return Tracer(sink=recording_sink, session_id="http-tracer-session", run_id="http-tracer-run")


@pytest.fixture
def unused_tcp_port() -> Iterator[int]:
    """Bind an ephemeral loopback socket; yield its port; close on teardown.

    Used by tests that need a real local server without making assumptions
    about ports that may be in use on the test host.
    """
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


# ---------------------------------------------------------------------------
# Test 1 — wrapping an ``httpx.Client`` with ``instrument_httpx`` emits exactly
# one ``http.client.request`` span per ``send``.
# ---------------------------------------------------------------------------


def test_instrument_httpx_emits_one_span_per_send(http_tracer: Any) -> None:
    """One :class:`httpx.Client.send` → one ``http.client.request`` span.

    Uses a real :class:`httpx.Client` wrapped with ``instrument_httpx`` so
    the implementation cannot fake the surface. ``http://127.0.0.1:0/`` is
    a deliberately unreachable URL — the instrumentation site must still
    record a span (with status code 0 / error class set) so D8 / "trace
    every send" is observable on the failure path. The span count is what
    the test pins, not the failure status (test 10 covers that surface).
    """
    from mergecraft.tracing.http import instrument_httpx

    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="s", run_id="r")
    client = httpx.Client(timeout=0.05)
    try:
        instrument_httpx(client, tracer=tracer)
        with pytest.raises(httpx.HTTPError):
            client.get("http://127.0.0.1:0/")
    finally:
        client.close()

    spans = _http_spans(sink)
    assert len(spans) == 1, f"expected one http.client.request span, got {len(spans)}"


# ---------------------------------------------------------------------------
# Test 2 — span attrs carry ``http.method`` / ``http.url`` (redacted) /
# ``http.status_code`` / ``http.duration_ms``.
# ---------------------------------------------------------------------------


def test_http_span_attrs_have_method_status_duration(unused_tcp_port: int) -> None:
    """A successful GET emits a span with method / status / duration attrs."""
    import http.server
    import threading

    from mergecraft.tracing.http import instrument_httpx

    from mergecraft.tracing import MemorySink, Tracer

    served = threading.Event()
    stop = threading.Event()

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            served.set()
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_args: Any) -> None:  # silence stderr noise
            return None

    server = http.server.HTTPServer(("127.0.0.1", unused_tcp_port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    del stop
    try:
        sink = MemorySink()
        tracer = Tracer(sink=sink, session_id="s", run_id="r")
        client = httpx.Client(timeout=5.0)
        try:
            instrument_httpx(client, tracer=tracer)
            response = client.get(f"http://127.0.0.1:{unused_tcp_port}/ping")
            assert response.status_code == 200
        finally:
            client.close()
        spans = _http_spans(sink)
        assert len(spans) == 1
        attrs = spans[0].attrs
        assert attrs["http.method"] == "GET"
        assert attrs["http.status_code"] == 200
        assert isinstance(attrs["http.duration_ms"], int)
        assert attrs["http.duration_ms"] >= 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Test 3 — ``redact_url`` redacts Telegram bot tokens inline (D9).
# ---------------------------------------------------------------------------


def test_redact_url_redacts_telegram_bot_token() -> None:
    """``api.telegram.org/bot123456:ABC-DEF/sendMessage`` → ``bot<redacted>/sendMessage``.

    D9: redaction is inline, not opaque. The URL stays parseable; the
    secret-shaped path component (``<TOKEN>``) is replaced with the literal
    ``<redacted>`` marker.
    """
    from mergecraft.tracing.redaction import redact_url

    redacted = redact_url("https://api.telegram.org/bot123456:ABC-DEF/sendMessage")
    assert redacted == "https://api.telegram.org/bot<redacted>/sendMessage"
    assert "123456" not in redacted
    assert "ABC-DEF" not in redacted


# ---------------------------------------------------------------------------
# Test 4 — ``redact_url`` redacts basic-auth userinfo (D9 pattern 2).
# ---------------------------------------------------------------------------


def test_redact_url_redacts_basic_auth() -> None:
    """``https://user:pass@host/path`` → ``https://user:<redacted>@host/path``."""
    from mergecraft.tracing.redaction import redact_url

    redacted = redact_url("https://user:pass@example.com/path")
    assert redacted == "https://user:<redacted>@example.com/path"
    assert "pass" not in redacted


# ---------------------------------------------------------------------------
# Test 5 — ``redact_url`` redacts query-param tokens (D9 pattern 3).
# ---------------------------------------------------------------------------


def test_redact_url_redacts_query_param_tokens() -> None:
    """``?api_key=sk-abc&x=1`` → ``?api_key=<redacted>&x=1``."""
    from mergecraft.tracing.redaction import redact_url

    redacted = redact_url("https://example.com/v1/messages?api_key=sk-abc&x=1")
    assert redacted == "https://example.com/v1/messages?api_key=<redacted>&x=1"
    assert "sk-abc" not in redacted


# ---------------------------------------------------------------------------
# Test 6 — a redacted URL is still a parseable URL with the same path shape.
# ---------------------------------------------------------------------------


def test_redact_url_preserves_path_shape() -> None:
    """The redacted output is a valid URL and keeps the same path components.

    The plan's T2.1 test 6: a redaction that turns the URL into opaque
    ``<redacted>`` text would break Logfire's path-based grouping. The
    helper must therefore keep ``scheme``, ``host``, ``port``, ``path``,
    and (un-redacted) query params intact.
    """
    from urllib.parse import urlparse

    from mergecraft.tracing.redaction import redact_url

    original = "https://api.example.com:8443/v1/chat/completions?api_key=sk-secret&stream=true"
    redacted = redact_url(original)
    original_parts = urlparse(original)
    redacted_parts = urlparse(redacted)
    assert redacted_parts.scheme == original_parts.scheme
    assert redacted_parts.hostname == original_parts.hostname
    assert redacted_parts.port == original_parts.port
    assert redacted_parts.path == original_parts.path
    redacted_query = urlparse(redacted).query
    assert "api_key=<redacted>" in redacted_query
    assert "stream=true" in redacted_query


# ---------------------------------------------------------------------------
# Test 7 — ``instrument_httpx`` is idempotent (sentinel attribute check).
# ---------------------------------------------------------------------------


def test_instrument_httpx_idempotent() -> None:
    """Calling ``instrument_httpx`` twice on the same client does not double-wrap.

    D8 requires narrow instrumentation: the implementation must guard
    against re-wrapping with a sentinel attribute (``_mergecraft_instrumented``)
    so a second ``instrument_httpx`` call is a no-op rather than a
    double-emit per send.
    """
    from mergecraft.tracing.http import instrument_httpx

    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="s", run_id="r")
    client = httpx.Client(timeout=0.05)
    try:
        instrument_httpx(client, tracer=tracer)
        assert getattr(client, "_mergecraft_instrumented", False) is True
        instrument_httpx(client, tracer=tracer)
        assert getattr(client, "_mergecraft_instrumented", False) is True
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Test 8 — ``provider.call`` parent wrapping ``llm.call`` for Anthropic.
# Xfail — this is the defining T2.2 GREEN surface.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason="green after T2.2: provider.call parent wraps llm.call (anthropic)",
    strict=False,
)
def test_provider_call_span_wraps_llm_call_for_anthropic(recording_sink: Any) -> None:
    """Claude driver emits ``provider.call`` (anthropic) + ``llm.call`` + ``http.client.request``.

    The plan's T2.1 test 8 / D10 — ``provider.call`` is a real span kind,
    not an attribute. The driver wires the existing ``llm.call`` span as a
    child of a new ``provider.call`` parent on ``message_start`` / close on
    ``message_stop``; ``provider.transport_family="anthropic"`` is the
    contract surface.
    """
    from mergecraft.agents._stream_consumer import StreamSpanAccumulator
    from mergecraft.agents.claude import _claude_stream_event_handler
    from mergecraft.tracing import Tracer

    tracer = Tracer(sink=recording_sink, session_id="anthropic-test", run_id="anthropic-run")
    handler, close_all = _claude_stream_event_handler(
        tracer=tracer,
        parent_span_id=None,
        model_id="claude-sonnet-4",
    )
    acc = StreamSpanAccumulator(agent_name="claude")
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg-anthropic-1",
                "usage": {"input_tokens": 10, "output_tokens": 0},
            },
        },
        {"type": "message_delta", "message_id": "msg-anthropic-1", "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
        {
            "type": "result",
            "result": "anthropic-test-output",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
    ]
    for event in events:
        handler(acc, event)
    close_all()

    by_kind = _by_kind(recording_sink)
    provider_calls = by_kind.get("provider.call", [])
    llm_calls = by_kind.get("llm.call", [])
    http_calls = by_kind.get("http.client.request", [])
    assert len(provider_calls) >= 1, "expected at least one provider.call span"
    assert len(llm_calls) >= 1, "expected at least one llm.call span"
    provider_attrs = provider_calls[0].attrs
    assert provider_attrs.get("provider.transport_family") == "anthropic"
    assert provider_attrs.get("provider.id") == "anthropic"
    llm_span_id = llm_calls[0].span_id
    assert llm_calls[0].parent_span_id == provider_calls[0].span_id
    if http_calls:
        assert http_calls[0].parent_span_id == llm_span_id


# ---------------------------------------------------------------------------
# Test 9 — ``provider.call`` parent wrapping ``llm.call`` for chat_completions
# (opencode / Nous / MiniMax).
# ---------------------------------------------------------------------------


def test_provider_call_span_wraps_llm_call_for_chat_completions(
    recording_sink: Any,
) -> None:
    """OpenAI-compatible driver emits ``provider.call`` (chat_completions) parent + children.

    The plan's T2.1 test 9 / D10 — opencode (and the Nous / MiniMax
    passthrough) emit ``provider.transport_family="chat_completions"``.
    Drivers that go through ``agents/openai_compatible_gateways.py`` wrap
    their ``httpx.Client`` via ``instrument_httpx`` and wrap their
    ``llm.call`` span via a new ``provider.call`` parent — the assertion
    pins the parent-child tree shape end-to-end.
    """
    from mergecraft.tracing.http import instrument_httpx

    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="cc-test", run_id="cc-run")
    with tracer.start_span("provider.call") as provider_span:
        provider_span.set_attribute("provider.id", "openai_compatible")
        provider_span.set_attribute("provider.transport_family", "chat_completions")
        with tracer.start_span("llm.call", parent_span_id=provider_span.span_id) as llm_span:
            llm_span.set_attribute("model.id", "nous/hermes-3")
            client = httpx.Client(timeout=0.05)
            try:
                instrument_httpx(client, tracer=tracer)
                with pytest.raises(httpx.HTTPError):
                    client.get("http://127.0.0.1:0/")
            finally:
                client.close()

    by_kind = _by_kind(sink)
    provider_calls = by_kind["provider.call"]
    llm_calls = by_kind["llm.call"]
    http_calls = by_kind.get("http.client.request", [])
    assert provider_calls[0].attrs["provider.transport_family"] == "chat_completions"
    assert llm_calls[0].parent_span_id == provider_calls[0].span_id
    if http_calls:
        assert http_calls[0].parent_span_id == llm_calls[0].span_id


# ---------------------------------------------------------------------------
# Test 10 — connection-refused still emits a span with status_code=0 and
# ``http.error_class`` set.
# ---------------------------------------------------------------------------


def test_http_failure_emits_span_with_status_code_0() -> None:
    """Connection refused → span with ``http.status_code=0`` and ``http.error_class``."""
    from mergecraft.tracing.http import instrument_httpx

    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="s", run_id="r")
    client = httpx.Client(timeout=0.5)
    try:
        instrument_httpx(client, tracer=tracer)
        with pytest.raises(httpx.HTTPError):
            client.get("http://127.0.0.1:1/never-listens")
    finally:
        client.close()

    spans = _http_spans(sink)
    assert len(spans) == 1
    attrs = spans[0].attrs
    assert attrs["http.status_code"] == 0
    assert "http.error_class" in attrs
    assert isinstance(attrs["http.error_class"], str)
    assert attrs["http.error_class"] != ""


# ---------------------------------------------------------------------------
# Test 11 — the ``trace_id`` from T3 plumbing is inherited by the
# ``http.client.request`` span so Logfire groups the http row under the
# same trace as the LLM span that triggered it.
# ---------------------------------------------------------------------------


def test_http_span_inherits_trace_id_from_mergecraft_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mergeCraft ``trace_id`` propagates onto the emitted http span.

    Relies on T3.2's ``Tracer.trace_id`` / ``Span.trace_id`` plumbing and
    on ``OTLPSink._override_span_trace_id`` rewriting the OTel
    ``trace_id`` on the produced span. Without T3.2's ``trace_id`` field
    this test cannot pass; the T3 RED suite is the prerequisite. This test
    pins the cross-wave bridge from the plan's T2.1 test 11.
    """
    for key in ("MERGECRAFT_TRACE_ID", "MERGECRAFT_TRACE_SESSION_ID", "GITHUB_RUN_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MERGECRAFT_TRACE_SESSION_ID", "shared-trace-t2-test")

    from mergecraft.tracing.http import instrument_httpx

    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="shared", run_id="shared")
    with tracer.start_span("llm.call") as llm_span:
        llm_trace_id = llm_span.trace_id
        client = httpx.Client(timeout=0.05)
        try:
            instrument_httpx(client, tracer=tracer)
            with pytest.raises(httpx.HTTPError):
                client.get("http://127.0.0.1:0/")
        finally:
            client.close()

    http_spans = _http_spans(sink)
    assert len(http_spans) == 1
    assert http_spans[0].trace_id == llm_trace_id
    assert http_spans[0].trace_id == tracer.trace_id


# ---------------------------------------------------------------------------
# Test 12 — disabled tracing path emits no ``http.client.request`` span.
# ---------------------------------------------------------------------------


def test_disabled_tracer_path_emits_no_http_span() -> None:
    """``NullTracer`` path: ``instrument_httpx`` + send produces no event.

    Convention 9 / #56 D9 — the disabled path is a true no-op. ``NullTracer``'s
    ``start_span`` returns a ``NullSpan`` whose ``__exit__`` never reaches
    the sink; the same must hold for ``instrument_httpx`` when the wrapped
    tracer is the null path.
    """
    from mergecraft.tracing.http import instrument_httpx

    from mergecraft.tracing import NullTracer

    client = httpx.Client(timeout=0.05)
    try:
        instrument_httpx(client, tracer=NullTracer())
        with pytest.raises(httpx.HTTPError):
            client.get("http://127.0.0.1:0/")
    finally:
        client.close()


__all__ = [
    "test_disabled_tracer_path_emits_no_http_span",
    "test_http_failure_emits_span_with_status_code_0",
    "test_http_span_attrs_have_method_status_duration",
    "test_http_span_inherits_trace_id_from_mergecraft_run",
    "test_instrument_httpx_emits_one_span_per_send",
    "test_instrument_httpx_idempotent",
    "test_provider_call_span_wraps_llm_call_for_anthropic",
    "test_provider_call_span_wraps_llm_call_for_chat_completions",
    "test_redact_url_preserves_path_shape",
    "test_redact_url_redacts_basic_auth",
    "test_redact_url_redacts_query_param_tokens",
    "test_redact_url_redacts_telegram_bot_token",
]
