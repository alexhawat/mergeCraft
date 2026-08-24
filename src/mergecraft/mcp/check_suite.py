"""get_check_suite_logs tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.ci.log_excerpt import analyze_log as _analyze_log
from mergecraft.ci.providers.github_actions import (
    GitHubActionsProvider,
    unbound_check_suite_logs,
)
from mergecraft.mcp.shared import ToolClass, execute, tool
from mergecraft.scm.github import github_client_from_scm

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

_GITHUB_PROVIDER = GitHubActionsProvider()


def get_check_suite_logs_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        check_suite_id = int(params["check_suite_id"])
        client = github_client_from_scm(ctx.scm)
        if client is None:
            return unbound_check_suite_logs(check_suite_id)
        try:
            runs = await client.list_workflow_runs_for_check_suite(
                ctx.repo.owner, ctx.repo.name, check_suite_id
            )
        except Exception as err:
            # Same fail-closed policy as ``run_ci_intelligence``: listing
            # failure is unavailable, not a raised tool error.
            return {
                "check_suite_id": check_suite_id,
                "message": str(err) or "check-suite run listing failed",
                "jobs": [],
                "available": False,
            }
        return await _GITHUB_PROVIDER.fetch_check_suite_logs(
            ctx, check_suite_id=check_suite_id, client=client, runs=runs
        )

    return tool(
        name="get_check_suite_logs",
        tool_class=ToolClass.REPOSITORY_READ,
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
