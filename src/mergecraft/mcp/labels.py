"""Label add/remove tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.mcp.shared import ToolClass, execute, get_http_status, tool

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def add_labels_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        issue_number = int(params["issue_number"])
        labels = list(params["labels"])
        result = await ctx.scm.add_labels(ctx.repo.owner, ctx.repo.name, issue_number, labels)
        logger.info("added labels {} to #{}", labels, issue_number)
        return {"success": True, "labels": [label.get("name") for label in result]}

    return tool(
        name="add_labels",
        tool_class=ToolClass.GITHUB_MUTATION,
        mutates=True,
        description=(
            "Add labels to a GitHub issue or pull request. "
            "Only use labels that already exist in the repository."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "issue_number": {"type": "number"},
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
            },
            "required": ["issue_number", "labels"],
            "additionalProperties": False,
        },
        execute=execute(_run, "add_labels"),
    )


def remove_labels_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        issue_number = int(params["issue_number"])
        await ctx.scm.get_issue(ctx.repo.owner, ctx.repo.name, issue_number)
        removed: list[str] = []
        for name in params["labels"]:
            try:
                await ctx.scm.delete(
                    f"/repos/{ctx.repo.owner}/{ctx.repo.name}/issues/{issue_number}/labels/{name}"
                )
                removed.append(str(name))
            except Exception as err:
                if get_http_status(err) != 404:
                    raise
        if removed:
            ctx.tool_state.was_updated = True
        logger.info("removed labels {} from #{}", removed, issue_number)
        return {"success": True, "removed": removed}

    return tool(
        name="remove_labels",
        tool_class=ToolClass.GITHUB_MUTATION,
        mutates=True,
        description="Remove labels from a GitHub issue or pull request.",
        input_schema={
            "type": "object",
            "properties": {
                "issue_number": {"type": "number"},
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
            },
            "required": ["issue_number", "labels"],
            "additionalProperties": False,
        },
        execute=execute(_run, "remove_labels"),
    )
