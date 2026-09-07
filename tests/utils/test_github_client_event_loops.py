"""One ``GitHubClient`` must survive being driven from more than one event loop.

PR #628 published its review and then lost *both* check-runs — including
``mergecraft-approval``, the one the merge gate reads — to a single warning:

    status checks: failed to resolve PR #628 head sha:
    <asyncio.locks.Event object ...> is bound to a different event loop

``ToolContext.scm`` wraps one ``httpx.AsyncClient``, and a run drives it from
two loops: the main loop and the MCP HTTP server's own loop in a daemon thread
(``mcp/server.py::_serve_in_thread``). httpx binds its connection-pool
primitives to whichever loop first sends a request, so the second loop raised,
``report_status_checks`` swallowed it, and the gate failed closed on an
approved review. The binding is lazy, which is why this was intermittent — the
same code approved #623 cleanly.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from mergecraft.utils.github import GitHubClient


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive is the whole point: the bug needs a pooled connection that
    # outlives the loop that opened it. HTTP/1.0 would close after each
    # response, leave the pool empty, and the second loop would never touch
    # the first loop's primitives.
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        body = b'{"head": {"sha": "deadbeef"}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        """Silence the stdlib access log."""


class _QuietServer(ThreadingHTTPServer):
    """A loopback server that cannot leak into another test's output.

    Two hardenings, both learned from a real CI failure. ``socketserver``
    writes "Exception occurred during processing of request ..." plus a
    traceback straight to ``sys.stderr``; when an unrelated test is running
    under a Click/Typer ``CliRunner``, that lands inside the runner's captured
    output and fails *its* assertions (``tests/cli/test_doctor.py``). And
    ``ThreadingHTTPServer`` defaults to ``daemon_threads = True``, which makes
    ``block_on_close`` False, so ``server_close()`` returns while per-connection
    handler threads are still alive — the keep-alive connection this module
    needs guarantees at least one is parked in ``rfile.readline()``.
    """

    daemon_threads = False  # so block_on_close is True and server_close() joins
    allow_reuse_address = True

    def handle_error(self, request: object, client_address: object) -> None:
        """Swallow handler errors instead of printing them to stderr."""


@pytest.fixture
def api_base_url() -> Iterator[str]:
    """A real loopback HTTP server, so the httpx connection pool is exercised.

    A mock or ASGI transport would not do: those bypass the pool, and the pool
    is precisely what carries the loop-bound primitives this test is about.
    """
    server = _QuietServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class _BackgroundLoop:
    """A live event loop in a daemon thread — ``mcp/server.py::_serve_in_thread``.

    The loop must stay *running* for the whole test, not be spun up and torn
    down per call. A closed loop produces a different error ("Event loop is
    closed"); the production failure needs the first loop still alive, holding
    the pooled connection's primitives, when the second loop reaches for it.
    """

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="mcp-like-loop", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=30)

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=5)


@pytest.fixture
def mcp_loop() -> Iterator[_BackgroundLoop]:
    background = _BackgroundLoop()
    try:
        yield background
    finally:
        background.close()


async def test_client_serves_a_second_event_loop_after_the_first(
    api_base_url: str, mcp_loop: _BackgroundLoop
) -> None:
    """The MCP loop goes first, then the publish path on the main loop must work.

    This is the #628 ordering exactly: MCP tools (``submit_review_verdict``,
    ``list_check_runs``) bind the client, then ``report_status_checks`` calls
    ``get_pull`` on the main loop.
    """
    client = GitHubClient("token", base_url=api_base_url)
    try:
        assert mcp_loop.run(client.get("/anything")) == {"head": {"sha": "deadbeef"}}
        # Before the per-loop fix this raised
        # "... is bound to a different event loop".
        assert await client.get("/anything") == {"head": {"sha": "deadbeef"}}
    finally:
        await client.aclose()


async def test_each_loop_gets_its_own_transport_and_reuses_it(
    api_base_url: str, mcp_loop: _BackgroundLoop
) -> None:
    """Per-loop binding, not per-request: the transport is cached by loop."""
    client = GitHubClient("token", base_url=api_base_url)
    try:
        await client.get("/anything")
        main_transport = client._active_client()
        assert client._active_client() is main_transport

        mcp_loop.run(client.get("/anything"))
        assert len(client._clients) == 2
        assert client._active_client() is main_transport
    finally:
        await client.aclose()


async def test_injected_client_is_returned_unchanged(
    api_base_url: str, mcp_loop: _BackgroundLoop
) -> None:
    """An injected transport keeps its caller-owned lifecycle and loop affinity."""
    import httpx

    injected = httpx.AsyncClient(base_url=api_base_url)
    client = GitHubClient("token", base_url=api_base_url, client=injected)
    try:
        assert client._active_client() is injected
        await client.aclose()
        # ``aclose`` is a no-op for an injected client — still usable.
        assert await client.get("/anything") == {"head": {"sha": "deadbeef"}}
    finally:
        await injected.aclose()


async def test_aclose_releases_every_per_loop_transport(
    api_base_url: str, mcp_loop: _BackgroundLoop
) -> None:
    """Closing must not leave another loop's pool behind."""
    client = GitHubClient("token", base_url=api_base_url)
    await client.get("/anything")
    mcp_loop.run(client.get("/anything"))
    assert len(client._clients) == 2
    await client.aclose()
    assert client._clients == {}
