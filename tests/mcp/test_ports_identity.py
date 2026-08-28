"""BR1.6 / BR7 — MCP port identity checks (MCB-27, D14)."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING

import pytest
import uvicorn
from fastapi import FastAPI

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.ports import MCP_HOST, wait_for_bound_port
from mergecraft.mcp.server import create_mcp_app, resolve_uvicorn_bind_port
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path


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


def _squat_port(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((MCP_HOST, port))
    sock.listen(1)
    return sock


def test_squatter_on_the_configured_port_is_not_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MCB-27: a squatter on ``MERGECRAFT_MCP_PORT`` must not be accepted as MCP."""
    from mergecraft.mcp.server import _serve_in_thread

    port = 38491
    squatter = _squat_port(port)
    monkeypatch.setenv("MERGECRAFT_MCP_PORT", str(port))
    try:
        assert resolve_uvicorn_bind_port() == 0
        app = create_mcp_app([], _tool_ctx(tmp_path))
        config = uvicorn.Config(app, host=MCP_HOST, port=port, log_level="warning")
        server, thread, _loop = _serve_in_thread(config, thread_name="br1-port-squat")
        try:
            with pytest.raises((RuntimeError, OSError)):
                wait_for_bound_port(server, port, timeout_s=1.0)
        finally:
            server.should_exit = True
            thread.join(timeout=2)
    finally:
        squatter.close()


def test_server_thread_failure_is_raised_not_swallowed(tmp_path: Path) -> None:
    """MCB-27: uvicorn startup failures must propagate to the caller."""
    from mergecraft.mcp.server import _serve_in_thread

    failing = FastAPI()

    @failing.on_event("startup")
    async def _boom() -> None:
        msg = "br1-forced-startup-failure"
        raise RuntimeError(msg)

    config = uvicorn.Config(failing, host=MCP_HOST, port=0, log_level="warning")
    server, thread, _loop = _serve_in_thread(config, thread_name="br1-startup-fail")
    try:
        with pytest.raises(RuntimeError, match=r"startup|failure|br1-forced-startup-failure"):
            wait_for_bound_port(server, 0, timeout_s=2.0)
    finally:
        server.should_exit = True
        thread.join(timeout=2)
