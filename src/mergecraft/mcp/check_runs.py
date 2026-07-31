"""list_check_runs and get_check_suite tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.mcp.shared import execute, tool

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def list_check_runs_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        ref = str(params["ref"])
        data = await ctx.github.list_check_suites_for_ref(ctx.repo.owner, ctx.repo.name, ref)
        return {
            "ref": ref,
            "total_count": data.get("total_count"),
            "check_suites": data.get("check_suites") or [],
        }

    return tool(
        name="list_check_runs",
        description=(
            "List GitHub check suites for a commit ref. Returns check suite ids, "
            "status, and conclusions so you can pick a check_suite_id for "
            "get_check_suite_logs."
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
        return await ctx.github.get_check_suite(
            ctx.repo.owner,
            ctx.repo.name,
            check_suite_id,
        )

    return tool(
        name="get_check_suite",
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
