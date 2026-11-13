"""mergeCraft MCP package — HTTP tool server and tool modules."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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

_EXPORT_MODULES = {
    "PayloadEvent": "mergecraft.mcp.context",
    "RepoIdentity": "mergecraft.mcp.context",
    "ResolvedPayload": "mergecraft.mcp.context",
    "ToolContext": "mergecraft.mcp.context",
    "build_common_tools": "mergecraft.mcp.server",
    "build_orchestrator_tools": "mergecraft.mcp.server",
    "build_reviewer_tools": "mergecraft.mcp.server",
    "build_verifier_tools": "mergecraft.mcp.server",
    "start_mcp_http_server": "mergecraft.mcp.server",
    "ToolClass": "mergecraft.mcp.shared",
    "ToolSpec": "mergecraft.mcp.shared",
    "tool": "mergecraft.mcp.shared",
    "ToolState": "mergecraft.mcp.tool_state",
    "init_tool_state": "mergecraft.mcp.tool_state",
    "primary_repo_state": "mergecraft.mcp.tool_state",
    "repo_key": "mergecraft.mcp.tool_state",
}

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


def __getattr__(name: str) -> Any:
    """Resolve public re-exports without loading unrelated runtime subsystems."""
    if name not in _EXPORT_MODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(_EXPORT_MODULES[name]), name)
    globals()[name] = value
    return value
