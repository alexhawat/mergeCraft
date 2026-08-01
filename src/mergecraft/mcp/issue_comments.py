"""get_issue_comments tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.mcp.shared import execute, tool
from mergecraft.mcp.tool_state import primary_repo_state

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def get_issue_comments_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        issue_number = int(params["issue_number"])
        primary_repo_state(ctx.tool_state).issue_number = issue_number
        comments = await ctx.github.list_issue_comments(
            ctx.repo.owner,
            ctx.repo.name,
            issue_number,
            headers={"Accept": "application/vnd.github.full+json"},
            params={"per_page": 100},
        )
        processed = [
            {
                "id": c.get("id"),
                "body": c.get("body"),
                "user": (c.get("user") or {}).get("login"),
            }
            for c in comments
        ]
        return {"issue_number": issue_number, "comments": processed, "count": len(processed)}

    return tool(
        name="get_issue_comments",
        description="Get all comments for a GitHub issue.",
        input_schema={
            "type": "object",
            "properties": {"issue_number": {"type": "number"}},
            "required": ["issue_number"],
            "additionalProperties": False,
        },
        execute=execute(_run, "get_issue_comments"),
    )
