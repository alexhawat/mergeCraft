"""Issue create/close/reopen tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.mcp.shared import ToolClass, execute, tool

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def create_issue_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        result = await ctx.github.create_issue(
            ctx.repo.owner,
            ctx.repo.name,
            title=str(params["title"]),
            body=str(params["body"]),
            labels=list(params.get("labels") or []),
            assignees=list(params.get("assignees") or []),
        )  # assignees via **extra
        logger.info("created issue #{}", result.get("number"))
        labels = result.get("labels") or []
        return {
            "success": True,
            "issueId": result.get("id"),
            "number": result.get("number"),
            "url": result.get("html_url"),
            "title": result.get("title"),
            "state": result.get("state"),
            "labels": [label if isinstance(label, str) else label.get("name") for label in labels],
            "assignees": [a.get("login") for a in (result.get("assignees") or [])],
        }

    return tool(
        name="create_issue",
        tool_class=ToolClass.GITHUB_MUTATION,
        mutates=True,
        description="Create a new GitHub issue",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
                "assignees": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "body"],
            "additionalProperties": False,
        },
        execute=execute(_run, "create_issue"),
    )


def close_issue_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        result = await ctx.github.update_issue(
            ctx.repo.owner,
            ctx.repo.name,
            int(params["issue_number"]),
            state="closed",
            state_reason=params["state_reason"],
        )
        ctx.tool_state.was_updated = True
        logger.info("closed issue #{}", params["issue_number"])
        return {
            "success": True,
            "number": result.get("number"),
            "url": result.get("html_url"),
            "state": result.get("state"),
            "stateReason": result.get("state_reason"),
        }

    return tool(
        name="close_issue",
        tool_class=ToolClass.GITHUB_MUTATION,
        mutates=True,
        description="Close a GitHub issue with a reason.",
        input_schema={
            "type": "object",
            "properties": {
                "issue_number": {"type": "number"},
                "state_reason": {
                    "type": "string",
                    "enum": ["completed", "not_planned", "duplicate"],
                },
            },
            "required": ["issue_number", "state_reason"],
            "additionalProperties": False,
        },
        execute=execute(_run, "close_issue"),
    )


def reopen_issue_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        result = await ctx.github.update_issue(
            ctx.repo.owner,
            ctx.repo.name,
            int(params["issue_number"]),
            state="open",
        )
        ctx.tool_state.was_updated = True
        return {
            "success": True,
            "number": result.get("number"),
            "url": result.get("html_url"),
            "state": result.get("state"),
        }

    return tool(
        name="reopen_issue",
        tool_class=ToolClass.GITHUB_MUTATION,
        mutates=True,
        description="Reopen a previously closed GitHub issue.",
        input_schema={
            "type": "object",
            "properties": {"issue_number": {"type": "number"}},
            "required": ["issue_number"],
            "additionalProperties": False,
        },
        execute=execute(_run, "reopen_issue"),
    )
