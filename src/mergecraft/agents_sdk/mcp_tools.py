"""In-process wrappers for mergeCraft public MCP tools (function-tool backend)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

from mergecraft.mcp.context_factory import minimal_tool_context
from mergecraft.mcp.public import PUBLIC_TOOL_NAMES, build_public_tools

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.shared import ToolSpec


def tool_context_for_workspace(
    repo_root: str,
    *,
    trust_tier: Literal["trusted", "untrusted"] = "trusted",
) -> ToolContext:
    """Build a public-MCP ``ToolContext`` rooted at ``repo_root``."""
    root = str(repo_root)
    return minimal_tool_context(
        root,
        payload_cwd=root,
        trust_tier=trust_tier,
    )


def public_tool_specs(ctx: ToolContext) -> dict[str, ToolSpec]:
    return {spec.name: spec for spec in build_public_tools(ctx)}


async def call_public_tool(
    ctx: ToolContext,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Invoke one public MCP tool in-process (same handlers as stdio MCP)."""
    if name not in PUBLIC_TOOL_NAMES:
        msg = f"unknown public tool {name!r}"
        raise KeyError(msg)
    spec = public_tool_specs(ctx)[name]
    result = await spec.execute(arguments or {})
    if result.is_error:
        text = result.content[0].get("text", "") if result.content else ""
        return {"error": text.removeprefix("Error: ").strip() or "tool failed"}
    text = result.content[0].get("text", "") if result.content else "{}"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"result": text}
    if isinstance(parsed, dict):
        return parsed
    return {"result": parsed}


__all__ = [
    "call_public_tool",
    "public_tool_specs",
    "tool_context_for_workspace",
]
