"""Fixtures that isolate verify tests from ambient env and provide a fake CDP host."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _isolate_github_event_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests are local unless they set the Actions event themselves.

    ``MERGECRAFT_CDP_URL`` is deliberately *not* cleared here: the named live
    test must honour the operator's configured endpoint, and its ``skipif``
    probes that same ambient value at collection. Tests that assert the default
    endpoint isolate it themselves with ``monkeypatch.setenv`` /
    ``monkeypatch.delenv``, which runs after this fixture.
    """
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)


def _json_body(payload: object) -> bytes:
    return json.dumps(payload).encode("utf-8")


class _FakeCdpHandler(BaseHTTPRequestHandler):
    """Serve the two CDP HTTP discovery routes a driver may probe."""

    def do_GET(self) -> None:
        if self.path == "/json/version":
            body = _json_body(
                {
                    "Browser": "FakeChrome/0.0.0",
                    "Protocol-Version": "1.3",
                    "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/fake",
                }
            )
        elif self.path == "/json/list":
            body = _json_body(
                [
                    {
                        "id": "fake-page",
                        "type": "page",
                        "url": "about:blank",
                        "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/fake",
                    }
                ]
            )
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        del args


@pytest.fixture
def fake_cdp_endpoint(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Run a local fake CDP HTTP endpoint and point ``MERGECRAFT_CDP_URL`` at it.

    The endpoint answers ``/json/version`` and ``/json/list`` so a reachable
    probe is deterministic without a real Chrome. It is not a websocket.
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeCdpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setenv("MERGECRAFT_CDP_URL", url)
    try:
        yield url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
