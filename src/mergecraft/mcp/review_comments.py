"""Review comment list / resolve tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.findings.threads import fetch_review_threads as _fetch_review_threads
from mergecraft.mcp.shared import ToolClass, execute, tool

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

_RESOLVE_THREAD = """
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread { id isResolved }
  }
}
"""


async def fetch_review_threads(
    ctx: ToolContext, pull_number: int, *, include_resolved: bool = False
) -> list[dict[str, Any]]:
    """Return a PR's review threads, normalized for both the tool and callers in-process."""
    page = await _fetch_review_threads(
        ctx.github,
        ctx.repo.owner,
        ctx.repo.name,
        pull_number,
        include_resolved=include_resolved,
    )
    return page.threads


async def resolve_review_thread(ctx: ToolContext, thread_id: str) -> bool:
    """Resolve one review thread; returns whether GitHub reports it resolved."""
    data = await ctx.github.graphql(_RESOLVE_THREAD, {"threadId": thread_id})
    thread = ((data or {}).get("resolveReviewThread") or {}).get("thread") or {}
    return bool(thread.get("isResolved", True))


def get_review_comments_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        pull_number = int(params["pull_number"])
        include_resolved = bool(params.get("include_resolved", False))
        threads = await fetch_review_threads(ctx, pull_number, include_resolved=include_resolved)
        return {
            "pull_number": pull_number,
            "threads": threads,
            "count": len(threads),
        }

    return tool(
        name="get_review_comments",
        tool_class=ToolClass.REVIEW_READ,
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
        tool_class=ToolClass.REVIEW_READ,
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
        is_resolved = await resolve_review_thread(ctx, thread_id)
        ctx.tool_state.was_updated = True
        return {
            "success": True,
            "threadId": thread_id,
            "isResolved": is_resolved,
        }

    return tool(
        name="resolve_review_thread",
        tool_class=ToolClass.REVIEW_WRITE,
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
