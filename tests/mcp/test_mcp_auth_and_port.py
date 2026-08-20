"""#283 / D15: per-run bearer (or Unix socket) + unguessable loopback port.

``tools/call`` and ``tools/list`` currently accept unauthenticated loopback
POSTs. Port allocation is ``MCP_PORT_START + randint(0, 49)`` (then a 100-wide
scan). W14 issues a per-run secret at MCP startup, rejects unauthenticated
``tools/list`` + ``tools/call`` (HTTP 401 or JSON-RPC ``-32600``), keeps
loopback, and replaces the 3764-band scan with ``bind(0)`` or
``secrets.randbelow`` over the ephemeral range.

``/health`` may stay unauthenticated. ``x-mergecraft-agent-id`` is
tracing-only — it is **not** the credential. ``MERGECRAFT_MCP_PORT`` stays.
"""

from __future__ import annotations

import inspect
import json
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pytest

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.server import (
    MCP_ENDPOINT,
    MCP_HOST,
    _select_port,
    start_mcp_http_server,
)
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

_LIST_PAYLOAD = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
_CALL_PAYLOAD = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {"name": "git", "arguments": {"command": "status"}},
}


def _tool_ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="unknown"),
            shell="restricted",
            push="restricted",
        ),
        github=GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


def _per_run_token(ctx: ToolContext) -> str:
    token = getattr(ctx, "mcp_auth_token", None)
    if isinstance(token, str) and token:
        return token
    pytest.fail("per-run MCP token was not issued at server startup (D15)")


def _rpc_post(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload).encode()
    req_headers = {"Content-Type": "application/json", **(headers or {})}
    request = Request(url, data=body, headers=req_headers, method="POST")
    try:
        with urlopen(request, timeout=5) as resp:
            raw = resp.read().decode()
            parsed: dict[str, Any] = json.loads(raw) if raw else {}
            return int(resp.status), parsed
    except HTTPError as exc:
        raw = exc.read().decode()
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {}
        return int(exc.code), parsed
    except URLError as exc:
        pytest.fail(f"MCP POST to {url} failed: {exc}")


def _is_auth_rejection(status: int, body: dict[str, Any]) -> bool:
    if status == 401:
        return True
    error = body.get("error")
    return isinstance(error, dict) and error.get("code") == -32600


def _is_tools_list_ok(status: int, body: dict[str, Any]) -> bool:
    if status != 200:
        return False
    result = body.get("result")
    return isinstance(result, dict) and isinstance(result.get("tools"), list)


def test_tools_list_and_call_require_per_run_token(tmp_path: Path) -> None:
    """W11.4: unauthenticated ``tools/list`` + ``tools/call`` fail; token succeeds."""
    ctx = _tool_ctx(tmp_path)
    url, stop = start_mcp_http_server(ctx)
    try:
        assert url.startswith(f"http://{MCP_HOST}:")
        status, body = _rpc_post(url, _LIST_PAYLOAD)
        assert _is_auth_rejection(status, body), (
            f"unauthenticated tools/list must be 401 or JSON-RPC -32600; "
            f"got status={status} body={body!r}"
        )

        status, body = _rpc_post(url, _CALL_PAYLOAD)
        assert _is_auth_rejection(status, body), (
            f"unauthenticated tools/call must be 401 or JSON-RPC -32600; "
            f"got status={status} body={body!r}"
        )

        status, body = _rpc_post(
            url,
            _LIST_PAYLOAD,
            headers={"x-mergecraft-agent-id": "claude"},
        )
        assert _is_auth_rejection(status, body), (
            "x-mergecraft-agent-id is tracing-only and must not authenticate tools/list"
        )

        token = _per_run_token(ctx)
        auth = {"Authorization": f"Bearer {token}"}
        status, body = _rpc_post(url, _LIST_PAYLOAD, headers=auth)
        assert _is_tools_list_ok(status, body), (
            f"authenticated tools/list must succeed; status={status} body={body!r}"
        )
        names = {entry["name"] for entry in body["result"]["tools"]}
        assert names, "authenticated tools/list returned an empty toolset"

        status, body = _rpc_post(url, _CALL_PAYLOAD, headers=auth)
        assert status == 200, body
        assert "error" not in body or body.get("error", {}).get("code") != -32600
    finally:
        stop()


def test_health_stays_unauthenticated(tmp_path: Path) -> None:
    """D15 control: ``/health`` may stay open; it is not the credential surface."""
    ctx = _tool_ctx(tmp_path)
    url, stop = start_mcp_http_server(ctx)
    try:
        parsed = urlparse(url)
        health = f"{parsed.scheme}://{parsed.netloc}/health"
        request = Request(health, method="GET")
        with urlopen(request, timeout=5) as resp:
            assert resp.status == 200
            payload = json.loads(resp.read().decode())
        assert payload.get("status") == "ok"
    finally:
        stop()


def test_select_port_is_not_3764_plus_fifty_wide_scan() -> None:
    """W11.4: allocator is not ``3764 + offset ∈ [0, 49]``."""
    src = inspect.getsource(_select_port)
    assert "randint(0, 49)" not in src
    assert "randrange(50)" not in src
    uses_ephemeral = (
        "bind((MCP_HOST, 0))" in src
        or "bind((MCP_HOST,0))" in src
        or "port=0" in src.replace(" ", "")
        or "randbelow" in src
    )
    assert uses_ephemeral, (
        "_select_port must use bind(0) or secrets.randbelow over the ephemeral "
        f"range; source was:\n{src}"
    )
    assert "MCP_PORT_START" not in src or "MERGECRAFT_MCP_PORT" in src


def test_mergecraft_mcp_port_override_still_honored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D15 control: explicit ``MERGECRAFT_MCP_PORT`` still wins when free."""
    from mergecraft.mcp import server as server_mod

    monkeypatch.setenv("MERGECRAFT_MCP_PORT", "41234")
    monkeypatch.setattr(server_mod, "_port_available", lambda _port: True)
    assert _select_port() == 41234


def test_started_server_port_is_loopback_and_not_the_3764_band(tmp_path: Path) -> None:
    """Live pin: returned URL stays loopback; port is not chosen from the 50-wide 3764 scan."""
    ctx = _tool_ctx(tmp_path)
    url, stop = start_mcp_http_server(ctx)
    try:
        parsed = urlparse(url)
        assert parsed.hostname == MCP_HOST
        assert parsed.port is not None
        band = set(range(3764, 3764 + 50))
        src = inspect.getsource(_select_port)
        if "randint(0, 49)" in src:
            pytest.fail("port allocator still scans 3764 + offset in [0, 49]")
        # bind(0) may coincidentally land in-band; the source pin above is the
        # contract. This live assertion only rejects the *returned* URL using
        # the old endpoint shape without a token surface.
        assert parsed.scheme == "http"
        assert url.startswith(f"http://{MCP_HOST}:")
        assert parsed.port not in band or "randbelow" in src or "bind(" in src
    finally:
        stop()


def test_mcp_endpoint_constant_is_still_slash_mcp() -> None:
    """D14 / D17: role paths hang off ``MCP_ENDPOINT``; do not rename it for auth."""
    assert MCP_ENDPOINT == "/mcp"


def test_unauthenticated_mixed_batch_with_notification_shaped_tools_call_returns_401(
    tmp_path: Path,
) -> None:
    """D15 / batch regression: bearer check fires at request edge regardless of ``id``.

    A batch that mixes a notification-shaped ``tools/call`` (no ``id``) with a
    normal request must still return 401 when the bearer token is absent — the
    auth check must not require ``id`` to be present.
    """
    ctx = _tool_ctx(tmp_path)
    url, stop = start_mcp_http_server(ctx)
    try:
        batch = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            # notification-shaped tools/call (no ``id``) — must not bypass auth
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "git", "arguments": {"command": "status"}},
            },
        ]
        status, body = _rpc_post(url, batch)
        assert _is_auth_rejection(status, body), (
            f"unauthenticated batch with notification-shaped tools/call must be 401; "
            f"got status={status} body={body!r}"
        )
    finally:
        stop()


def test_authenticated_mixed_batch_skips_notification_shaped_tools_call(
    tmp_path: Path,
) -> None:
    """D15 / batch regression: even with a valid token, notification-shaped tools/call is skipped.

    A notification carries no ``id`` and must not produce a response and must not
    be executed, even in an authenticated batch. Only the request (with ``id``)
    receives a response.
    """
    ctx = _tool_ctx(tmp_path)
    url, stop = start_mcp_http_server(ctx)
    try:
        token = _per_run_token(ctx)
        batch = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "git", "arguments": {"command": "status"}},
            },
        ]
        status, body = _rpc_post(url, batch, headers={"Authorization": f"Bearer {token}"})
        assert status == 200
        assert isinstance(body, list), f"batch response must be a list; got {body!r}"
        response_ids = [entry.get("id") for entry in body]
        assert response_ids == [1], (
            f"notification-shaped tools/call must be skipped (no response produced); "
            f"got response ids={response_ids}"
        )
    finally:
        stop()
