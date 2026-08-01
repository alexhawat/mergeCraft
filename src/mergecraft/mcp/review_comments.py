"""Review comment list / resolve tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.mcp.shared import execute, tool

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

_RESOLVE_THREAD = """
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread { id isResolved }
  }
}
"""

_THREADS_QUERY = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        nodes {
          id
          isResolved
          isOutdated
          comments(first: 20) {
            nodes {
              databaseId
              body
              author { login }
              path
              line
              originalLine
              createdAt
            }
          }
        }
      }
    }
  }
}
"""


def get_review_comments_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        pull_number = int(params["pull_number"])
        include_resolved = bool(params.get("include_resolved", False))
        data = await ctx.github.graphql(
            _THREADS_QUERY,
            {
                "owner": ctx.repo.owner,
                "repo": ctx.repo.name,
                "number": pull_number,
            },
        )
        nodes = ((data or {}).get("repository") or {}).get("pullRequest", {}).get(
            "reviewThreads", {}
        ).get("nodes") or []
        threads: list[dict[str, Any]] = []
        for node in nodes:
            if node.get("isResolved") and not include_resolved:
                continue
            comments = [
                {
                    "id": c.get("databaseId"),
                    "body": c.get("body"),
                    "author": (c.get("author") or {}).get("login"),
                    "path": c.get("path"),
                    "line": c.get("line") or c.get("originalLine"),
                    "createdAt": c.get("createdAt"),
                }
                for c in ((node.get("comments") or {}).get("nodes") or [])
            ]
            threads.append(
                {
                    "threadId": node.get("id"),
                    "isResolved": node.get("isResolved"),
                    "isOutdated": node.get("isOutdated"),
                    "comments": comments,
                }
            )
        return {
            "pull_number": pull_number,
            "threads": threads,
            "count": len(threads),
        }

    return tool(
        name="get_review_comments",
        description=(
            "List review threads (inline comments) for a pull request, including "
            "thread IDs for resolve_review_thread."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "pull_number": {"type": "number"},
                "include_resolved": {"type": "boolean"},
            },
            "required": ["pull_number"],
            "additionalProperties": False,
        },
        execute=execute(_run, "get_review_comments"),
    )


def list_pull_request_reviews_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        pull_number = int(params["pull_number"])
        reviews = await ctx.github.list_reviews(
            ctx.repo.owner, ctx.repo.name, pull_number, params={"per_page": 100}
        )
        return {
            "pull_number": pull_number,
            "reviews": [
                {
                    "id": r.get("id"),
                    "state": r.get("state"),
                    "body": r.get("body"),
                    "user": (r.get("user") or {}).get("login"),
                    "submitted_at": r.get("submitted_at"),
                    "commit_id": r.get("commit_id"),
                }
                for r in reviews
            ],
            "count": len(reviews),
        }

    return tool(
        name="list_pull_request_reviews",
        description="List submitted reviews for a pull request.",
        input_schema={
            "type": "object",
            "properties": {"pull_number": {"type": "number"}},
            "required": ["pull_number"],
            "additionalProperties": False,
        },
        execute=execute(_run, "list_pull_request_reviews"),
    )


def resolve_review_thread_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        thread_id = str(params["thread_id"])
        data = await ctx.github.graphql(_RESOLVE_THREAD, {"threadId": thread_id})
        thread = ((data or {}).get("resolveReviewThread") or {}).get("thread") or {}
        ctx.tool_state.was_updated = True
        return {
            "success": True,
            "threadId": thread.get("id", thread_id),
            "isResolved": thread.get("isResolved", True),
        }

    return tool(
        name="resolve_review_thread",
        mutates=True,
        description="Resolve a pull request review thread by GraphQL thread ID.",
        input_schema={
            "type": "object",
            "properties": {"thread_id": {"type": "string"}},
            "required": ["thread_id"],
            "additionalProperties": False,
        },
        execute=execute(_run, "resolve_review_thread"),
    )
