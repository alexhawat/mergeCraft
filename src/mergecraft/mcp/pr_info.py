"""get_pull_request tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger

from mergecraft.mcp.shared import ToolClass, execute, tool

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

_CLOSING_ISSUES_QUERY = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      closingIssuesReferences(first: 10) {
        nodes { number title }
      }
    }
  }
}
"""


def _closing_issues_from(gql: Any) -> list[dict[str, Any]]:
    """Read ``closingIssuesReferences`` nodes, skipping any that are malformed."""
    level: Any = gql
    for key in ("repository", "pullRequest", "closingIssuesReferences", "nodes"):
        level = level.get(key) if isinstance(level, dict) else None
    if not isinstance(level, list):
        return []
    return [
        {"number": node["number"], "title": node["title"]}
        for node in level
        if isinstance(node, dict) and "number" in node and "title" in node
    ]


def get_pull_request_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        pull_number = int(params["pull_number"])
        data = await ctx.scm.get_pull(ctx.repo.owner, ctx.repo.name, pull_number)
        closing: list[dict[str, Any]] = []
        closing_unavailable = False
        try:
            gql = await ctx.scm.graphql(
                _CLOSING_ISSUES_QUERY,
                {
                    "owner": ctx.repo.owner,
                    "repo": ctx.repo.name,
                    "number": pull_number,
                },
            )
        # HTTP status and transport failures (httpx), GraphQL errors and an
        # SCM without GraphQL (RuntimeError), a missing token or an unparseable
        # body (ValueError). Anything else is a bug and propagates.
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            logger.warning(
                "get_pull_request: closing-issues lookup failed for #{}; "
                "reporting closingIssuesUnavailable: {}",
                pull_number,
                exc,
            )
            closing_unavailable = True
        else:
            closing = _closing_issues_from(gql)

        head = data.get("head") or {}
        base = data.get("base") or {}
        head_repo = (head.get("repo") or {}).get("full_name")
        base_repo = (base.get("repo") or {}).get("full_name")
        return {
            "number": data.get("number"),
            "url": data.get("html_url"),
            "title": data.get("title"),
            "body": data.get("body"),
            "state": data.get("state"),
            "draft": data.get("draft"),
            "merged": data.get("merged"),
            "maintainerCanModify": data.get("maintainer_can_modify"),
            "base": base.get("ref"),
            "head": head.get("ref"),
            "isFork": head_repo != base_repo,
            "author": (data.get("user") or {}).get("login"),
            "assignees": [a.get("login") for a in (data.get("assignees") or [])],
            "labels": [label.get("name") for label in (data.get("labels") or [])],
            "closingIssues": closing,
            **({"closingIssuesUnavailable": True} if closing_unavailable else {}),
        }

    return tool(
        name="get_pull_request",
        tool_class=ToolClass.REPOSITORY_READ,
        description=(
            "Retrieve PR metadata (title, body, state, branches, author, labels, "
            "linked issues). To checkout a PR branch locally, use checkout_pr instead."
        ),
        input_schema={
            "type": "object",
            "properties": {"pull_number": {"type": "number"}},
            "required": ["pull_number"],
            "additionalProperties": False,
        },
        execute=execute(_run, "get_pull_request"),
    )
