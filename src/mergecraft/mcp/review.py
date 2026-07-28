"""create_pull_request_review tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger

from mergecraft.mcp.comment import add_footer
from mergecraft.mcp.shared import execute, tool
from mergecraft.mcp.tool_state import ApprovalRecord, ReviewRecord, primary_repo_state
from mergecraft.review_taxonomy import stamp_finding_fingerprint

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding
    from mergecraft.mcp.context import ToolContext


def format_analyzer_inline_body(
    finding: Finding,
    *,
    effort: str = "Quick win",
    verification_note: str | None = None,
) -> str:
    """Format an analyzer-sourced inline comment with tool citation and confidence (W7.6)."""
    tag = f"_{finding.category}_ | _{finding.severity}_ | _{effort}_ | _{finding.confidence}_"
    citation = f"`{finding.tool}` `{finding.rule_id}`"
    lines = [tag, "", f"{finding.message}", "", f"Source: {citation}."]
    if verification_note:
        lines.extend(["", verification_note.strip()])
    return "\n".join(lines)


def enrich_analyzer_comment_body(body: str) -> str:
    """Return review comment bodies unchanged (formatting is upstream)."""
    return body


def create_pull_request_review_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        pull_number = int(params["pull_number"])
        approved = bool(params.get("approved"))
        request_changes = bool(params.get("request_changes"))
        if approved and request_changes:
            msg = "approved and request_changes are mutually exclusive"
            raise ValueError(msg)

        body = params.get("body")
        comments = list(params.get("comments") or [])
        if not body and not comments:
            return {
                "success": True,
                "skipped": True,
                "reason": "empty review (no body and no comments)",
            }

        primary = primary_repo_state(ctx.tool_state)
        primary.issue_number = pull_number

        if ctx.tool_state.review and primary.checkout_sha:
            if ctx.tool_state.review.reviewed_sha == primary.checkout_sha:
                return {
                    "success": True,
                    "skipped": True,
                    "reason": (
                        f"review {ctx.tool_state.review.id} already submitted for "
                        f"sha {primary.checkout_sha} this session"
                    ),
                    "reviewId": ctx.tool_state.review.id,
                }

        event = "COMMENT"
        if approved and ctx.pr_approve_enabled:
            event = "APPROVE"
        elif request_changes:
            event = "REQUEST_CHANGES"

        payload: dict[str, Any] = {"event": event}
        if body:
            payload["body"] = add_footer(ctx, str(body))
        if params.get("commit_id"):
            payload["commit_id"] = params["commit_id"]
        elif primary.checkout_sha:
            payload["commit_id"] = primary.checkout_sha

        inline: list[dict[str, Any]] = []
        for c in comments:
            item: dict[str, Any] = {
                "path": c["path"],
                "body": c.get("body") or "",
            }
            if c.get("suggestion"):
                suggestion = str(c["suggestion"])
                item["body"] = (
                    f"{item['body']}\n```suggestion\n{suggestion}\n```"
                    if item["body"]
                    else f"```suggestion\n{suggestion}\n```"
                )
            # Stamped server-side so every finding is dedup-able across runs even
            # when the model forgets — an IncrementalReview can then tell a
            # re-raised finding from a new one without re-reading every thread.
            item["body"] = stamp_finding_fingerprint(path=item["path"], body=item["body"])
            if "line" in c:
                item["line"] = int(c["line"])
            if "side" in c:
                item["side"] = c["side"]
            if "start_line" in c:
                item["start_line"] = int(c["start_line"])
                item["start_side"] = c.get("start_side") or c.get("side") or "RIGHT"
            inline.append(item)
        if inline:
            payload["comments"] = inline

        approve_fallback = False
        try:
            result = await ctx.github.create_review(
                ctx.repo.owner, ctx.repo.name, pull_number, **payload
            )
        except httpx.HTTPStatusError as exc:
            if event != "APPROVE" or exc.response.status_code != 422:
                raise
            logger.info(
                "APPROVE review rejected with 422 on PR #{}; falling back to COMMENT",
                pull_number,
            )
            fallback = dict(payload)
            fallback["event"] = "COMMENT"
            result = await ctx.github.create_review(
                ctx.repo.owner, ctx.repo.name, pull_number, **fallback
            )
            approve_fallback = True
        review_id = int(result["id"])
        ctx.tool_state.review = ReviewRecord(
            id=review_id,
            node_id=str(result.get("node_id") or ""),
            reviewed_sha=payload.get("commit_id"),
        )
        ctx.tool_state.approval = ApprovalRecord(
            would_approve=approved,
            sha=payload.get("commit_id"),
        )
        ctx.tool_state.was_updated = True
        logger.info("submitted review {} on PR #{}", review_id, pull_number)
        response: dict[str, Any] = {
            "success": True,
            "reviewId": review_id,
            "url": result.get("html_url"),
            "state": result.get("state"),
            "commitId": payload.get("commit_id"),
        }
        if approve_fallback:
            response["approveFallbackDueTo422"] = True
            response["requestedReviewState"] = "APPROVE"
        return response

    return tool(
        name="create_pull_request_review",
        mutates=True,
        description=(
            "Submit a review for an existing pull request. "
            "Set approved:true to approve, request_changes:true to block, or neither "
            "for a plain comment review."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "pull_number": {"type": "number"},
                "body": {"type": "string"},
                "approved": {"type": "boolean"},
                "request_changes": {"type": "boolean"},
                "commit_id": {"type": "string"},
                "comments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "line": {"type": "number"},
                            "side": {"type": "string", "enum": ["LEFT", "RIGHT"]},
                            "body": {"type": "string"},
                            "suggestion": {
                                "type": "string",
                                "description": (
                                    "Complete replacement text for the anchored line range, "
                                    "correctly indented, no diff markers and no prose. Wrapped "
                                    "server-side in a GitHub ```suggestion fence so the author "
                                    "gets a one-click Commit suggestion button. Omit when the fix "
                                    "spans multiple hunks or files, or when you cannot produce "
                                    "the exact replacement text — a suggestion that does not "
                                    "apply cleanly is worse than none."
                                ),
                            },
                            "start_line": {"type": "number"},
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["pull_number"],
            "additionalProperties": False,
        },
        execute=execute(_run, "create_pull_request_review"),
    )
