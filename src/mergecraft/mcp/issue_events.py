"""get_issue_events tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.mcp.shared import ToolClass, execute, tool
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.utils.github import GITHUB_LIST_PAGE_SIZE, paginate_github_bare_array

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

_RELEVANT = frozenset({"cross_referenced", "referenced"})


def get_issue_events_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        issue_number = int(params["issue_number"])
        primary_repo_state(ctx.tool_state).issue_number = issue_number
        timeline_path = f"/repos/{ctx.repo.owner}/{ctx.repo.name}/issues/{issue_number}/timeline"
        timeline_headers = {"Accept": "application/vnd.github+json"}

        async def _fetch_page(page: int) -> Any:
            return await ctx.scm.get(
                timeline_path,
                headers=timeline_headers,
                params={"per_page": GITHUB_LIST_PAGE_SIZE, "page": page},
            )

        events = await paginate_github_bare_array(
            _fetch_page,
            path_for_log=timeline_path,
            strict_rows=False,
        )
        parsed: list[dict[str, Any]] = []
        for event in events:
            etype = event.get("event")
            if etype not in _RELEVANT:
                continue
            item: dict[str, Any] = {"event": etype}
            if "id" in event:
                item["id"] = event["id"]
            actor = event.get("actor") or event.get("user")
            if actor:
                item["actor"] = actor.get("login")
            if "created_at" in event:
                item["created_at"] = event["created_at"]
            if etype == "cross_referenced" and event.get("source"):
                source = event["source"]
                issue = source.get("issue")
                pr = source.get("pull_request")
                item["source"] = {
                    "type": source.get("type"),
                    "issue": (
                        {
                            "number": issue.get("number"),
                            "title": issue.get("title"),
                            "html_url": issue.get("html_url"),
                        }
                        if issue
                        else None
                    ),
                    "pull_request": (
                        {
                            "number": pr.get("number"),
                            "title": pr.get("title"),
                            "html_url": pr.get("html_url"),
                        }
                        if pr
                        else None
                    ),
                }
            if etype == "referenced":
                item["commit_id"] = event.get("commit_id")
                item["commit_url"] = event.get("commit_url")
            parsed.append(item)
        return {"issue_number": issue_number, "events": parsed, "count": len(parsed)}

    return tool(
        name="get_issue_events",
        tool_class=ToolClass.REPOSITORY_READ,
        description=(
            "Get timeline events for a GitHub issue that aren't reflected in current "
            "state (cross-references and commit references)."
        ),
        input_schema={
            "type": "object",
            "properties": {"issue_number": {"type": "number"}},
            "required": ["issue_number"],
            "additionalProperties": False,
        },
        execute=execute(_run, "get_issue_events"),
    )
