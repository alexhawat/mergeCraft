"""get_check_suite_logs tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.ci.log_excerpt import analyze_log as _analyze_log
from mergecraft.ci.providers.github_actions import GitHubActionsProvider
from mergecraft.mcp.shared import execute, tool

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

_GITHUB_PROVIDER = GitHubActionsProvider()


def get_check_suite_logs_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        check_suite_id = int(params["check_suite_id"])
        return await _GITHUB_PROVIDER.fetch_check_suite_logs(ctx, check_suite_id=check_suite_id)

    return tool(
        name="get_check_suite_logs",
        description=(
            "Get workflow run logs for a failed check suite. Returns a log_index, "
            "excerpt, and full_log_path."
        ),
        input_schema={
            "type": "object",
            "properties": {"check_suite_id": {"type": "number"}},
            "required": ["check_suite_id"],
            "additionalProperties": False,
        },
        execute=execute(_run, "get_check_suite_logs"),
    )


__all__ = ["_analyze_log", "get_check_suite_logs_tool"]
