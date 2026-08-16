"""Issue/PR comment tools: create, edit, reply, report_progress."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.mcp.shared import ToolClass, execute, tool
from mergecraft.mcp.tool_state import ProgressComment, ReviewReplyRecord, primary_repo_state
from mergecraft.utils.learnings import (
    ensure_learnings_review_delta,
    merge_learnings_delta_into_review_body,
)

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def _footer(ctx: ToolContext) -> str:
    parts = ["\n\n---\n", "*via mergecraft*"]
    if ctx.tool_state.model:
        parts.append(f" · `{ctx.tool_state.model}`")
    if ctx.run_id is not None:
        parts.append(
            f" · [run](https://github.com/{ctx.repo.owner}/{ctx.repo.name}"
            f"/actions/runs/{ctx.run_id})"
        )
    return "".join(parts)


def add_footer(ctx: ToolContext, body: str) -> str:
    cleaned = body.rstrip()
    if "*via mergecraft*" in cleaned:
        return cleaned
    return f"{cleaned}{_footer(ctx)}"


def create_issue_comment_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        issue_number = int(params["issueNumber"])
        body = add_footer(ctx, str(params["body"]))
        result = await ctx.github.create_issue_comment(
            ctx.repo.owner, ctx.repo.name, issue_number, body
        )
        ctx.tool_state.was_updated = True
        logger.info("created comment {}", result.get("id"))
        comment_type = params.get("type")
        if comment_type == "Plan" and result.get("id"):
            link = f"[Implement plan ➔](#implement-plan-{issue_number}-{result['id']})"
            plan_body = f"{str(params['body']).rstrip()}{_footer(ctx)} · {link}"
            result = await ctx.github.update_issue_comment(
                ctx.repo.owner, ctx.repo.name, int(result["id"]), plan_body
            )
        return {
            "success": True,
            "commentId": result.get("id"),
            "url": result.get("html_url"),
            "body": result.get("body"),
        }

    return tool(
        name="create_issue_comment",
        tool_class=ToolClass.GITHUB_MUTATION,
        mutates=True,
        description=(
            "Create a comment on a GitHub issue or PR. "
            "For the current run's answer/progress/plan use report_progress instead."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "issueNumber": {"type": "number", "description": "the issue number"},
                "body": {"type": "string", "description": "the comment body"},
                "type": {
                    "type": "string",
                    "enum": ["Plan", "Comment"],
                    "description": "Plan: standalone plan comment. Comment: regular (default).",
                },
            },
            "required": ["issueNumber", "body"],
            "additionalProperties": False,
        },
        execute=execute(_run, "create_issue_comment"),
    )


def edit_issue_comment_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        comment_id = int(params["commentId"])
        body = add_footer(ctx, str(params["body"]))
        result = await ctx.github.update_issue_comment(
            ctx.repo.owner, ctx.repo.name, comment_id, body
        )
        ctx.tool_state.was_updated = True
        return {
            "success": True,
            "commentId": result.get("id"),
            "url": result.get("html_url"),
            "body": result.get("body"),
        }

    return tool(
        name="edit_issue_comment",
        tool_class=ToolClass.GITHUB_MUTATION,
        mutates=True,
        description="Edit a GitHub issue comment by its ID",
        input_schema={
            "type": "object",
            "properties": {
                "commentId": {"type": "number"},
                "body": {"type": "string"},
            },
            "required": ["commentId", "body"],
            "additionalProperties": False,
        },
        execute=execute(_run, "edit_issue_comment"),
    )


def reply_to_review_comment_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        pull_number = int(params["pull_number"])
        comment_id = int(params["comment_id"])
        body_with_footer = add_footer(ctx, str(params["body"]))
        existing = ctx.tool_state.review_replies.get(comment_id)
        if existing and existing.body_with_footer == body_with_footer:
            return {
                "success": True,
                "skipped": True,
                "reason": existing.body_with_footer
                and (
                    f"reply {existing.comment_id} with identical body was already "
                    "posted in this session; ignoring duplicate call"
                ),
                "commentId": existing.comment_id,
                "url": existing.url,
            }
        _ = pull_number  # API reply endpoint is comment-scoped
        result = await ctx.github.create_review_comment_reply(
            ctx.repo.owner,
            ctx.repo.name,
            comment_id,
            body_with_footer,
        )
        rid = int(result["id"])
        ctx.tool_state.review_replies[comment_id] = ReviewReplyRecord(
            comment_id=rid,
            url=result.get("html_url"),
            body_with_footer=body_with_footer,
        )
        ctx.tool_state.was_updated = True
        return {
            "success": True,
            "commentId": rid,
            "url": result.get("html_url"),
            "body": result.get("body"),
        }

    return tool(
        name="reply_to_review_comment",
        tool_class=ToolClass.GITHUB_MUTATION,
        mutates=True,
        description=("Reply to a pull request review comment. Keep replies to one short sentence."),
        input_schema={
            "type": "object",
            "properties": {
                "pull_number": {"type": "number"},
                "comment_id": {"type": "number"},
                "body": {"type": "string"},
            },
            "required": ["pull_number", "comment_id", "body"],
            "additionalProperties": False,
        },
        execute=execute(_run, "reply_to_review_comment"),
    )


def report_progress_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        body = str(params["body"])
        target_plan = bool(params.get("target_plan_comment"))
        if ctx.tool_state.progress_comment is False and not target_plan:
            return {
                "success": True,
                "action": "skipped",
                "message": "progress comment was deleted; skipping",
            }

        issue_number = primary_repo_state(ctx.tool_state).issue_number
        if issue_number is None:
            issue_number = ctx.payload.event.issue_number
        if issue_number is None:
            return {
                "success": True,
                "action": "skipped",
                "message": (
                    "progress recorded (no GitHub comment created - no associated issue/PR)"
                ),
            }

        await ensure_learnings_review_delta(ctx.tool_state)
        body_with_delta = merge_learnings_delta_into_review_body(ctx.tool_state, body)
        body_with_footer = add_footer(ctx, body_with_delta)

        if target_plan and ctx.tool_state.existing_plan_comment_id:
            result = await ctx.github.update_issue_comment(
                ctx.repo.owner,
                ctx.repo.name,
                ctx.tool_state.existing_plan_comment_id,
                body_with_footer,
            )
            action = "updated"
        elif isinstance(ctx.tool_state.progress_comment, ProgressComment):
            result = await ctx.github.update_issue_comment(
                ctx.repo.owner,
                ctx.repo.name,
                int(ctx.tool_state.progress_comment.id),
                body_with_footer,
            )
            action = "updated"
        else:
            result = await ctx.github.create_issue_comment(
                ctx.repo.owner, ctx.repo.name, issue_number, body_with_footer
            )
            ctx.tool_state.progress_comment = ProgressComment(id=str(result["id"]), type="issue")
            action = "created"

        ctx.tool_state.last_progress_body = body
        ctx.tool_state.was_updated = True
        if not target_plan:
            ctx.tool_state.final_summary_written = True
        logger.info("{} progress comment {}", action, result.get("id"))
        return {
            "success": True,
            "action": action,
            "commentId": result.get("id"),
            "url": result.get("html_url"),
            "body": result.get("body"),
        }

    return tool(
        name="report_progress",
        tool_class=ToolClass.REVIEW_WRITE,
        mutates=True,
        description=(
            "Share progress on the associated GitHub issue/PR. "
            "The first call creates a comment; subsequent calls update it in place."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body": {"type": "string"},
                "target_plan_comment": {
                    "type": "boolean",
                    "description": "when true, update the existing plan comment instead",
                },
            },
            "required": ["body"],
            "additionalProperties": False,
        },
        execute=execute(_run, "report_progress"),
    )


__all__ = [
    "add_footer",
    "create_issue_comment_tool",
    "edit_issue_comment_tool",
    "reply_to_review_comment_tool",
    "report_progress_tool",
]
