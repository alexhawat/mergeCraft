"""mergeCraft MCP package — HTTP tool server and tool modules."""

from __future__ import annotations

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.server import (
    build_common_tools,
    build_orchestrator_tools,
    build_reviewer_tools,
    build_verifier_tools,
    start_mcp_http_server,
)
from mergecraft.mcp.shared import ToolClass, ToolSpec, tool
from mergecraft.mcp.tool_state import (
    ToolState,
    init_tool_state,
    primary_repo_state,
    repo_key,
)

__all__ = [
    "PayloadEvent",
    "RepoIdentity",
    "ResolvedPayload",
    "ToolClass",
    "ToolContext",
    "ToolSpec",
    "ToolState",
    "build_common_tools",
    "build_orchestrator_tools",
    "build_reviewer_tools",
    "build_verifier_tools",
    "init_tool_state",
    "primary_repo_state",
    "repo_key",
    "start_mcp_http_server",
    "tool",
]
