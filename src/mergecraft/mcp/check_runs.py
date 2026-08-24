"""list_check_runs and get_check_suite tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.mcp.shared import ToolClass, execute, tool
from mergecraft.utils.github import require_github_listed

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def _with_suite_id(run: dict[str, Any]) -> dict[str, Any]:
    """Lift a run's parent-suite id to the top level beside its own ``id``.

    ``get_check_suite_logs`` takes a *suite* id, which GitHub nests at
    ``check_suite.id`` while the run's own id sits at ``id`` — an invitation to
    pass the wrong one that four lines of tool description used to argue
    against. The nested field is left in place for callers already reading it.
    """
    suite = run.get("check_suite")
    suite_id = suite.get("id") if isinstance(suite, dict) else None
    if suite_id is None:
        return run
    return {**run, "check_suite_id": suite_id}


def list_check_runs_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        ref = str(params["ref"])
        listed = require_github_listed(
            await ctx.scm.list_check_runs_for_ref(ctx.repo.owner, ctx.repo.name, ref)
        )
        if listed.incomplete:
            # Same fail-closed policy as check-suite logs / CI intelligence /
            # gate substitution: a truncated walk must not look like a complete
            # catalog (silent total_count + partial check_runs).
            return {
                "ref": ref,
                "incomplete": True,
                "error": "check-run listing incomplete",
                "total_count": listed.total_count,
            }
        return {
            "ref": ref,
            "total_count": listed.total_count,
            "check_runs": [_with_suite_id(run) for run in listed.items],
        }

    return tool(
        name="list_check_runs",
        tool_class=ToolClass.REPOSITORY_READ,
        description=(
            "List GitHub check runs for a commit ref — one entry per run with its "
            "name, status, conclusion, and the check_suite_id to pass on to "
            "get_check_suite_logs or get_check_suite."
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
