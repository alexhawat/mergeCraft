"""Shared helpers for lane E — agent credential broker RED tests (plan 18 W1)."""

from __future__ import annotations

import importlib
import json
import threading
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

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
NON_MODEL_PATHS = ("/v1/files", "/admin", "/healthz")

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


class MockModelUpstream:
    """Loopback OpenAI-shaped upstream that records Authorization headers."""

    def __init__(self, *, redirect_to: str | None = None) -> None:
        self._redirect_to = redirect_to
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._host = "127.0.0.1"
        self._port = 0
        self.authorization_headers: list[str] = []
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

            def _record_auth(self) -> None:
                header = self.headers.get("Authorization", "")
                with upstream._lock:
                    upstream.authorization_headers.append(header)

            def do_POST(self) -> None:
                self._record_auth()
                if redirect_to is not None:
                    self.send_response(HTTPStatus.FOUND)
                    self.send_header("Location", redirect_to)
                    self.end_headers()
                    return
                body = json.dumps(
                    {
                        "id": "chatcmpl-stub",
                        "object": "chat.completion",
                        "choices": [
                            {"index": 0, "message": {"role": "assistant", "content": "ok"}}
                        ],
                    }
                ).encode()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                self._record_auth()
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


def broker_config_for_upstream(
    module: Any,
    upstream: MockModelUpstream,
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


def codex_module_path() -> Any:
    return SRC_ROOT / "agents" / "codex.py"
