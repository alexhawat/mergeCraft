"""Shared helpers for lane E — agent credential broker RED tests (plan 18 W1)."""

from __future__ import annotations

import gzip
import http.client
import importlib
import json
import threading
import time
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx
import pytest

from tests.evidence.support import sample_minimal_packet_dict
from tests.support.dead_package_wiring import SRC_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterator

BROKER_MODULE = "mergecraft.security.broker"

# Fixture credential — must never appear outside the parent process.
REAL_OPENAI_API_KEY_FIXTURE = "sk-live-run-fixture-openai-never-leak-18"

EVIL_UPSTREAM_HOST = "evil.example"
MODEL_PATH = "/v1/chat/completions"
RESPONSES_PATH = "/v1/responses"
CODEX_WIRE_API_SUFFIX = "responses"
NON_MODEL_PATHS = ("/v1/files", "/admin", "/healthz")

# PR #594 — broker upstream read timeout must exceed httpx's default 30s ceiling.
UPSTREAM_SLOW_RESPONSE_SECONDS = 31.0

LANE_B_SANDBOX_SYMBOLS = (
    "_operator_sandbox_override",
    "_sandbox_is_disabled_by_operator",
    "_sandbox_mode",
    "user_namespace_failure_hint",
)

W2_XFAIL = pytest.mark.xfail(reason="green after W2: credential broker", strict=False)
W3_XFAIL = pytest.mark.xfail(reason="green after W3: Codex broker wire-up", strict=False)


def load_broker_module() -> Any:
    """Import ``mergecraft.security.broker`` or fail with a clear message."""
    try:
        return importlib.import_module(BROKER_MODULE)
    except ImportError as exc:
        pytest.fail(f"{BROKER_MODULE} not implemented: {exc}")


def require_broker_symbol(module: Any, name: str) -> Any:
    if not hasattr(module, name):
        pytest.fail(f"{BROKER_MODULE}.{name} not implemented")
    return getattr(module, name)


@contextmanager
def capture_loguru_messages(*, level: str = "DEBUG") -> Iterator[list[str]]:
    """Attach a loguru sink; detach on exit."""
    from loguru import logger as loguru_logger

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda msg: captured.append(str(msg)), level=level)
    try:
        yield captured
    finally:
        loguru_logger.remove(sink_id)


def serialized_evidence_packet_fixture(*, error_detail: str) -> str:
    """Minimal merge-evidence JSON with a broker error field for redaction checks."""
    payload = sample_minimal_packet_dict()
    payload["run_health"] = {
        "broker": {
            "status": "error",
            "detail": error_detail,
        }
    }
    return json.dumps(payload)


def _snapshot_request_headers(handler: BaseHTTPRequestHandler) -> dict[str, str]:
    return {name: value for name, value in handler.headers.items()}


def _consume_request_body(handler: BaseHTTPRequestHandler) -> None:
    """Drain the request body so HTTP/1.1 keep-alive reuse is not poisoned."""
    raw_length = handler.headers.get("Content-Length", "0") or "0"
    try:
        length = int(raw_length)
    except ValueError:
        return
    if length > 0:
        handler.rfile.read(length)


class MockModelUpstream:
    """Loopback OpenAI-shaped upstream that records Authorization headers."""

    def __init__(
        self,
        *,
        redirect_to: str | None = None,
        gzip_response: bool = False,
    ) -> None:
        self._redirect_to = redirect_to
        self._gzip_response = gzip_response
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._host = "127.0.0.1"
        self._port = 0
        self.authorization_headers: list[str] = []
        self.request_header_maps: list[dict[str, str]] = []
        self._lock = threading.Lock()

    @property
    def base_url(self) -> str:
        if self._httpd is None:
            raise RuntimeError("upstream not started")
        return f"http://{self._host}:{self._port}/v1"

    @property
    def origin(self) -> str:
        if self._httpd is None:
            raise RuntimeError("upstream not started")
        return f"http://{self._host}:{self._port}"

    def start(self) -> None:
        redirect_to = self._redirect_to
        upstream = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: object) -> None:
                return

            def _record_request(self) -> None:
                header = self.headers.get("Authorization", "")
                headers = _snapshot_request_headers(self)
                with upstream._lock:
                    upstream.authorization_headers.append(header)
                    upstream.request_header_maps.append(headers)

            def do_POST(self) -> None:
                self._record_request()
                _consume_request_body(self)
                if redirect_to is not None:
                    self.send_response(HTTPStatus.FOUND)
                    self.send_header("Location", redirect_to)
                    self.end_headers()
                    return
                payload = {
                    "id": "chatcmpl-stub",
                    "object": "chat.completion",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
                }
                if self.path.rstrip("/").endswith("/responses"):
                    payload = {
                        "id": "resp-stub",
                        "object": "response",
                        "output": [{"type": "message", "content": "ok"}],
                    }
                body = json.dumps(payload).encode()
                if upstream._gzip_response:
                    body = gzip.compress(body)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                if upstream._gzip_response:
                    self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                self._record_request()
                _consume_request_body(self)
                if redirect_to is not None:
                    self.send_response(HTTPStatus.FOUND)
                    self.send_header("Location", redirect_to)
                    self.end_headers()
                    return
                body = b'{"data":[]}'
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._httpd = ThreadingHTTPServer((self._host, 0), _Handler)
        self._port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> MockModelUpstream:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


class SlowModelUpstream:
    """Loopback upstream that stays silent longer than httpx's 30s default timeout."""

    def __init__(
        self,
        *,
        delay_seconds: float = UPSTREAM_SLOW_RESPONSE_SECONDS,
    ) -> None:
        self._delay_seconds = delay_seconds
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._host = "127.0.0.1"
        self._port = 0
        self.authorization_headers: list[str] = []
        self.request_header_maps: list[dict[str, str]] = []
        self._lock = threading.Lock()

    @property
    def base_url(self) -> str:
        if self._httpd is None:
            raise RuntimeError("upstream not started")
        return f"http://{self._host}:{self._port}/v1"

    @property
    def origin(self) -> str:
        if self._httpd is None:
            raise RuntimeError("upstream not started")
        return f"http://{self._host}:{self._port}"

    def start(self) -> None:
        delay_seconds = self._delay_seconds
        upstream = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: object) -> None:
                return

            def do_POST(self) -> None:
                headers = _snapshot_request_headers(self)
                with upstream._lock:
                    upstream.authorization_headers.append(self.headers.get("Authorization", ""))
                    upstream.request_header_maps.append(headers)
                _consume_request_body(self)
                time.sleep(delay_seconds)
                body = json.dumps(
                    {
                        "id": "chatcmpl-slow",
                        "object": "chat.completion",
                        "choices": [
                            {"index": 0, "message": {"role": "assistant", "content": "slow-ok"}}
                        ],
                    }
                ).encode()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._httpd = ThreadingHTTPServer((self._host, 0), _Handler)
        self._port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> SlowModelUpstream:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


class StreamingSSEUpstream:
    """Loopback upstream that emits SSE chunks over time (streaming contract probe)."""

    def __init__(
        self,
        *,
        chunk_count: int = 5,
        inter_chunk_delay: float = 0.15,
    ) -> None:
        self._chunk_count = chunk_count
        self._inter_chunk_delay = inter_chunk_delay
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._host = "127.0.0.1"
        self._port = 0
        self.authorization_headers: list[str] = []
        self.request_header_maps: list[dict[str, str]] = []
        self.chunks_sent = 0
        # F2 (#759) — emit-time channel. Each chunk's departure time on this
        # process's monotonic clock, appended in emission order. The
        # incrementality assertion compares a client-observed arrival against
        # the *next* upstream emission, so a buffering relay is caught
        # structurally instead of by racing a wall-clock constant.
        self.chunk_emit_monotonic: list[float] = []
        self._lock = threading.Lock()

    @property
    def base_url(self) -> str:
        if self._httpd is None:
            raise RuntimeError("upstream not started")
        return f"http://{self._host}:{self._port}/v1"

    @property
    def origin(self) -> str:
        if self._httpd is None:
            raise RuntimeError("upstream not started")
        return f"http://{self._host}:{self._port}"

    @property
    def expected_stream_duration(self) -> float:
        return self._inter_chunk_delay * max(self._chunk_count - 1, 0)

    def start(self) -> None:
        chunk_count = self._chunk_count
        inter_chunk_delay = self._inter_chunk_delay
        upstream = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: object) -> None:
                return

            def do_POST(self) -> None:
                headers = _snapshot_request_headers(self)
                with upstream._lock:
                    upstream.authorization_headers.append(self.headers.get("Authorization", ""))
                    upstream.request_header_maps.append(headers)
                _consume_request_body(self)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                for index in range(chunk_count):
                    if index:
                        time.sleep(inter_chunk_delay)
                    chunk = f'data: {{"chunk": {index}}}\n\n'.encode()
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    emitted_at = time.monotonic()
                    with upstream._lock:
                        upstream.chunks_sent += 1
                        upstream.chunk_emit_monotonic.append(emitted_at)

        self._httpd = ThreadingHTTPServer((self._host, 0), _Handler)
        self._port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> StreamingSSEUpstream:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


def assert_chunks_observed_before_next_emit(
    *,
    observed_monotonic: dict[int, float],
    emit_monotonic: list[float],
) -> None:
    """F2 (#759) — structural SSE incrementality assertion.

    Chunk ``n`` must reach the client before the upstream emits chunk ``n+1``.
    Both sides are observed times on one monotonic clock, so there is no
    constant margin to race: a buffering relay that holds the stream until the
    upstream finishes makes every client arrival fall after the later
    emissions, while a relay that forwards as it reads keeps every arrival
    ahead of the next emission.

    Raises:
        AssertionError: When any observed chunk arrived after the next chunk
            was emitted, or when no ordered pair could be checked.
    """
    assert len(emit_monotonic) >= 2, "upstream must emit at least two chunks"
    checked = 0
    for index in sorted(observed_monotonic):
        if index + 1 >= len(emit_monotonic):
            continue
        observed_at = observed_monotonic[index]
        next_emitted_at = emit_monotonic[index + 1]
        assert observed_at < next_emitted_at, (
            f"client observed chunk {index} at {observed_at:.4f} but upstream emitted "
            f"chunk {index + 1} at {next_emitted_at:.4f} — the broker buffered the stream"
        )
        checked += 1
    assert checked >= 1, (
        "no ordered chunk pair was observable; the relay may have coalesced every chunk"
    )


def codex_provider_base_url(handle: Any) -> str:
    """Return the ``model_providers`` base URL Codex uses with ``wire_api = responses``."""
    base = getattr(handle, "base_url", None)
    if not isinstance(base, str):
        host = getattr(handle, "host", "127.0.0.1")
        port = handle.port
        base = f"http://{host}:{port}"
    normalized = base.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized
    return f"{normalized}/v1"


def broker_config_for_upstream(
    module: Any,
    upstream: MockModelUpstream | SlowModelUpstream | StreamingSSEUpstream,
    *,
    api_key: str = REAL_OPENAI_API_KEY_FIXTURE,
) -> Any:
    """Build a ``CredentialBrokerConfig`` for a loopback upstream fixture."""
    config_cls = require_broker_symbol(module, "CredentialBrokerConfig")
    parsed = urlparse(upstream.origin)
    host = parsed.hostname or "127.0.0.1"
    return config_cls(
        upstream_base_url=upstream.base_url,
        api_key=api_key,
        run_upstream_hosts=frozenset({host}),
    )


def assert_credential_absent(text: str, credential: str = REAL_OPENAI_API_KEY_FIXTURE) -> None:
    assert credential not in text, "real API credential leaked into output"


def post_absolute_url_to_broker(
    handle: Any,
    absolute_url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any] | None = None,
) -> httpx.Response:
    """POST to the loopback broker using an absolute-form request-target.

    ``httpx`` resolves absolute URLs itself and sends origin-form paths when
    connecting directly, so absolute-URL rewrite probes must dial the broker
    with :func:`http.client.HTTPConnection.request` and an absolute ``url``.
    """
    host = getattr(handle, "host", "127.0.0.1")
    port = handle.port
    body_bytes = b""
    request_headers = dict(headers)
    if json_body is not None:
        body_bytes = json.dumps(json_body).encode()
        request_headers.setdefault("Content-Type", "application/json")
    if body_bytes:
        request_headers.setdefault("Content-Length", str(len(body_bytes)))

    conn = http.client.HTTPConnection(host, port, timeout=10)
    try:
        conn.request("POST", absolute_url, body=body_bytes, headers=request_headers)
        raw = conn.getresponse()
        content = raw.read()
        response_headers = {key: value for key, value in raw.getheaders()}
    finally:
        conn.close()

    return httpx.Response(
        status_code=raw.status,
        headers=response_headers,
        content=content,
        request=httpx.Request("POST", absolute_url),
    )


def codex_module_path() -> Any:
    return SRC_ROOT / "agents" / "codex.py"
