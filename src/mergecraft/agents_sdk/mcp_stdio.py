"""Optional stdio MCP server wiring for the OpenAI Agents SDK."""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.mcp.server import MCPServerStdio, MCPServerStdioParams


def mergecraft_public_mcp_stdio_params(*, cwd: str | None = None) -> MCPServerStdioParams:
    """Parameters for ``MCPServerStdio`` targeting mergeCraft public MCP.

    Spawns ``mergecraft mcp serve --role public --transport stdio``. Requires the
    ``mergecraft`` CLI on ``PATH``; prefer in-process function tools from
    :func:`mergecraft.agents_sdk.review_agent` when embedding inside Python.
    """
    command = ["mergecraft", "mcp", "serve", "--role", "public", "--transport", "stdio"]
    params: MCPServerStdioParams = {"command": command[0], "args": command[1:]}
    if cwd:
        params["cwd"] = cwd
    return params


def mergecraft_public_mcp_stdio_server(*, cwd: str | None = None) -> MCPServerStdio:
    """Return a connected ``MCPServerStdio`` for mergeCraft public tools."""
    _require_agents_sdk()
    from agents.mcp import MCPServerStdio

    return MCPServerStdio(params=mergecraft_public_mcp_stdio_params(cwd=cwd))


def _require_agents_sdk() -> None:
    if importlib.util.find_spec("agents") is None:
        msg = (
            "OpenAI Agents SDK is not installed. "
            "Install mergecraft with the optional extra: pip install 'mergecraft-action[agents]'"
        )
        raise ImportError(msg)


__all__ = [
    "mergecraft_public_mcp_stdio_params",
    "mergecraft_public_mcp_stdio_server",
]
