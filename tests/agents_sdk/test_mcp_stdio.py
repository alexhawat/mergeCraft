"""Stdio MCP wiring for Agents SDK."""

from __future__ import annotations

import pytest

pytest.importorskip("agents")

from mergecraft.agents_sdk.mcp_stdio import (
    mergecraft_public_mcp_stdio_params,
    mergecraft_public_mcp_stdio_server,
)


def test_mergecraft_public_mcp_stdio_params_shape() -> None:
    params = mergecraft_public_mcp_stdio_params(cwd="/tmp/repo")
    assert params["command"] == "mergecraft"
    assert params["args"][:3] == ["mcp", "serve", "--role"]
    assert params["cwd"] == "/tmp/repo"


def test_mergecraft_public_mcp_stdio_server_uses_params() -> None:
    server = mergecraft_public_mcp_stdio_server(cwd="/tmp/repo")
    assert server.params.command == "mergecraft"
