"""get_pull_request tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.mcp.shared import execute, tool

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


def get_pull_request_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        pull_number = int(params["pull_number"])
        data = await ctx.github.get_pull(ctx.repo.owner, ctx.repo.name, pull_number)
        closing: list[dict[str, Any]] = []
        try:
            gql = await ctx.github.graphql(
                _CLOSING_ISSUES_QUERY,
                {
                    "owner": ctx.repo.owner,
                    "repo": ctx.repo.name,
                    "number": pull_number,
                },
            )
            nodes = ((gql or {}).get("repository") or {}).get("pullRequest", {}).get(
                "closingIssuesReferences", {}
            ).get("nodes") or []
            closing = [{"number": n["number"], "title": n["title"]} for n in nodes]
        except Exception:
            closing = []

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
        }

    return tool(
        name="get_pull_request",
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
