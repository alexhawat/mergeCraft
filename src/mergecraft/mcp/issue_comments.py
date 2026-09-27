"""get_issue_comments tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.mcp.list_pages import collect_list_pages
from mergecraft.mcp.shared import ToolClass, execute, tool
from mergecraft.mcp.tool_state import primary_repo_state

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def get_issue_comments_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        issue_number = int(params["issue_number"])
        primary_repo_state(ctx.tool_state).issue_number = issue_number

        async def _page(query: dict[str, Any]) -> list[dict[str, Any]]:
            return await ctx.scm.list_issue_comments(
                ctx.repo.owner,
                ctx.repo.name,
                issue_number,
                headers={"Accept": "application/vnd.github.full+json"},
                params=query,
            )

        listing = await collect_list_pages(_page, label=f"issue #{issue_number} comment")
        processed = [
            {
                "id": c.get("id"),
                "body": c.get("body"),
                "user": (c.get("user") or {}).get("login"),
            }
            for c in listing.rows
        ]
        response: dict[str, Any] = {
            "issue_number": issue_number,
            "comments": processed,
            "count": len(processed),
        }
        if listing.incomplete:
            response["incomplete"] = True
        return response

    return tool(
        name="get_issue_comments",
        tool_class=ToolClass.REPOSITORY_READ,
        description=(
            "Get the comments on a GitHub issue or pull request, oldest first, reading "
            "every page. If the listing hits the page cap the response carries "
            "incomplete: true and holds only the oldest comments."
        ),
        input_schema={
            "type": "object",
            "properties": {"issue_number": {"type": "number"}},
            "required": ["issue_number"],
            "additionalProperties": False,
        },
        execute=execute(_run, "get_issue_comments"),
    )
