"""list_check_runs and get_check_suite tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.mcp.shared import ToolClass, execute, tool

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def list_check_runs_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        ref = str(params["ref"])
        data = await ctx.scm.list_check_runs_for_ref(ctx.repo.owner, ctx.repo.name, ref)
        return {
            "ref": ref,
            "total_count": data.get("total_count"),
            "check_runs": data.get("check_runs") or [],
        }

    return tool(
        name="list_check_runs",
        tool_class=ToolClass.REPOSITORY_READ,
        description=(
            "List GitHub check runs for a commit ref. Returns one entry per run with "
            "its name, status, and conclusion, so you can see which individual job "
            "failed rather than only the suite rollup. Each run's top-level id is a "
            "check *run* id; the id of its parent suite is nested at check_suite.id. "
            "Pass that nested check_suite.id — never the top-level id — as the "
            "check_suite_id argument to get_check_suite_logs or get_check_suite."
        ),
        input_schema={
            "type": "object",
            "properties": {"ref": {"type": "string", "description": "Commit SHA or ref."}},
            "required": ["ref"],
            "additionalProperties": False,
        },
        execute=execute(_run, "list_check_runs"),
    )


def get_check_suite_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        check_suite_id = int(params["check_suite_id"])
        return await ctx.scm.get_check_suite(
            ctx.repo.owner,
            ctx.repo.name,
            check_suite_id,
        )

    return tool(
        name="get_check_suite",
        tool_class=ToolClass.REPOSITORY_READ,
        description="Fetch one GitHub check suite by id (status, conclusion, head SHA).",
        input_schema={
            "type": "object",
            "properties": {"check_suite_id": {"type": "number"}},
            "required": ["check_suite_id"],
            "additionalProperties": False,
        },
        execute=execute(_run, "get_check_suite"),
    )


__all__ = ["get_check_suite_tool", "list_check_runs_tool"]
