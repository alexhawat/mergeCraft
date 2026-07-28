"""get_issue tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.mcp.shared import execute, tool
from mergecraft.mcp.tool_state import primary_repo_state

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def get_issue_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        issue_number = int(params["issue_number"])
        data = await ctx.github.get_issue(
            ctx.repo.owner,
            ctx.repo.name,
            issue_number,
            headers={"Accept": "application/vnd.github.full+json"},
        )
        primary_repo_state(ctx.tool_state).issue_number = issue_number
        hints: list[str] = []
        if int(data.get("comments") or 0) > 0:
            hints.append("use get_issue_comments to retrieve all comments for this issue")
        hints.append("use get_issue_events to retrieve cross-references and commit references")
        labels = data.get("labels") or []
        return {
            "number": data.get("number"),
            "url": data.get("html_url"),
            "title": data.get("title"),
            "body": data.get("body"),
            "state": data.get("state"),
            "locked": data.get("locked"),
            "labels": [label if isinstance(label, str) else label.get("name") for label in labels],
            "assignees": [a.get("login") for a in (data.get("assignees") or [])],
            "user": (data.get("user") or {}).get("login"),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "closed_at": data.get("closed_at"),
            "comments": data.get("comments"),
            "milestone": (data.get("milestone") or {}).get("title")
            if data.get("milestone")
            else None,
            "pull_request": data.get("pull_request"),
            "hints": hints,
        }

    return tool(
        name="get_issue",
        description="Retrieve GitHub issue information by issue number.",
        input_schema={
            "type": "object",
            "properties": {"issue_number": {"type": "number"}},
            "required": ["issue_number"],
            "additionalProperties": False,
        },
        execute=execute(_run, "get_issue"),
    )
