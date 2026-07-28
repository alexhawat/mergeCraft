"""Subagent mutates deny + native FS denies (ported from subagentToolGates / nativeFsDenies)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.mcp.server import build_orchestrator_tools

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.shared import JsonSchema

# OpenCode Wildcard dialect write denies for the entire .git tree
GIT_NATIVE_WRITE_DENY_OPENCODE: dict[str, str] = {
    ".git": "deny",
    ".git/*": "deny",
    "*/.git": "deny",
    "*/.git/*": "deny",
}

GIT_NATIVE_READ_DENY_OPENCODE: dict[str, str] = {
    ".git/config": "deny",
}

CLAUDE_READ_TOOLS = ("Read", "Grep", "Glob")

GIT_NATIVE_WRITE_DENY_CLAUDE: list[str] = [
    "Edit(.git)",
    "Edit(.git/**)",
    "Edit(**/.git)",
    "Edit(**/.git/**)",
]

GIT_NATIVE_READ_DENY_CLAUDE: list[str] = [f"{tool}(.git/config)" for tool in CLAUDE_READ_TOOLS]


def subagent_denied_tool_names(
    ctx: ToolContext,
    output_schema: JsonSchema | None = None,
) -> list[str]:
    """Canonical bare names of every state-mutating MCP tool for this run."""
    names = [t.name for t in build_orchestrator_tools(ctx, output_schema) if t.mutates]
    if not names:
        msg = (
            "subagent deny list derived empty — no MCP tool is marked mutates=True. "
            "refusing to start with the subagent gate effectively disabled."
        )
        raise RuntimeError(msg)
    return names


def build_claude_native_fs_denies(
    extra_secret_paths: list[str] | None = None,
) -> list[str]:
    denies = [*GIT_NATIVE_WRITE_DENY_CLAUDE, *GIT_NATIVE_READ_DENY_CLAUDE]
    for path in extra_secret_paths or []:
        denies.append(f"Read({path})")
        denies.append(f"Edit({path})")
    return denies


def build_opencode_native_fs_permission() -> dict[str, object]:
    return {
        "edit": {"*": "allow", **GIT_NATIVE_WRITE_DENY_OPENCODE},
        "read": {"*": "allow", **GIT_NATIVE_READ_DENY_OPENCODE},
    }
