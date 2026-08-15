"""create_pull_request_review tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger

from mergecraft.mcp.comment import add_footer
from mergecraft.mcp.review_comments import fetch_review_threads, resolve_review_thread
from mergecraft.mcp.shared import execute, tool
from mergecraft.mcp.tool_state import ApprovalRecord, ReviewRecord, primary_repo_state
from mergecraft.mcp.verdict import (
    ReviewPhase,
    record_validated_terminal_submission,
    stamp_review_phase_on_active_span,
)
from mergecraft.review_resolution import finding_fingerprints_in, resolvable_thread_ids
from mergecraft.review_taxonomy import stamp_finding_fingerprint
from mergecraft.types import INCREMENTAL_REVIEW_MODE
from mergecraft.utils.learnings import (
    ensure_learnings_review_delta,
    merge_learnings_delta_into_review_body,
)

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


_FRESH_PR_TRIGGERS: frozenset[str] = frozenset(
    {"pull_request_opened", "pull_request_ready_for_review"}
)


def _is_rereview_trigger(trigger: str | None) -> bool:
    """Return True iff the run's trigger is a re-review (not a fresh PR).

    A re-review is any trigger that is **not** a fresh PR — synchronize,
    review_requested, review_submitted, review_comment, issue_comment, or
    similar. The trigger vocabulary is in
    ``mergecraft.utils.payload.PayloadTrigger``; the two values that
    name a fresh PR are the ones we exclude.

    Args:
        trigger: The trigger string from the run's payload event, or
            ``None`` for non-GitHub / offline runs.

    Returns:
        True when the trigger is not a fresh PR. Returns False when
        the trigger is unknown / unset — an unknown trigger is treated
        as a fresh PR so we never surface the suggestion on a run
        whose re-review status we cannot prove.
    """
    if not trigger:
        return False
    return trigger not in _FRESH_PR_TRIGGERS


def _maybe_suggest_eval_add(ctx: ToolContext) -> None:
    """Log a one-line suggestion to add the run to the eval bank (#44, W12.4).

    Fires when:

    - ``ctx.suggest_eval_add`` is True (opt-in via action input).
    - The trust tier is ``trusted`` (the suggestion is never surfaced
      on fork PRs or untrusted runs).
    - The trigger is a re-review (not a fresh PR; fresh PRs do not
      produce a *rejected / reverted* failure mode yet).
    - The run produced no positive findings.

    The function only logs — it never auto-adds. The eval bank is for
    *operator review*, not auto-capture.
    """
    if not getattr(ctx, "suggest_eval_add", False):
        return
    if ctx.trust_tier != "trusted":
        return
    trigger = ctx.payload.event.trigger
    if not _is_rereview_trigger(trigger):
        return
    # Positive signal: any analyzer finding attributed to the PR. The
    # analyzer pipeline writes into ``tool_state.analyzer_run.findings``
    # (a list of dicts); a missing or empty list means the run found
    # nothing.
    analyzer_run = getattr(ctx.tool_state, "analyzer_run", None)
    positive_findings = bool(getattr(analyzer_run, "findings", None))
    if positive_findings:
        return
    logger.info(
        "» suggest_eval_add: re-review produced no positive findings; "
        "consider capturing this run as a case via `mergecraft eval add` "
        "(never auto-added; #44, W12.4)",
    )


async def _resolve_fixed_finding_threads(
    ctx: ToolContext, *, pull_number: int, posted_bodies: list[str]
) -> int:
    """Close threads for findings the new commits fixed (C4).

    Runs only on a re-review that knows which paths moved since the last reviewed
    commit. A thread is closed when mergeCraft raised it, nobody else replied, its
    file was touched by the new commits, and the review just posted did not raise
    it again — i.e. the code the finding pointed at changed and the finding is
    gone. Everything here is advisory: a failure logs and the review still stands.
    """
    if ctx.tool_state.selected_mode != INCREMENTAL_REVIEW_MODE:
        return 0
    primary = primary_repo_state(ctx.tool_state)
    changed_paths = set(primary.incremental_changed_paths or ())
    if not changed_paths:
        return 0
    current: set[str] = set()
    for body in posted_bodies:
        current |= finding_fingerprints_in(body)
    try:
        threads = await fetch_review_threads(ctx, pull_number)
    except Exception as err:  # advisory cleanup; never fails a posted review
        logger.info("finding resolution: listing review threads soft-failed: {}", err)
        return 0
    targets = resolvable_thread_ids(
        threads, current_fingerprints=frozenset(current), changed_paths=changed_paths
    )
    resolved = 0
    for thread_id in targets:
        try:
            await resolve_review_thread(ctx, thread_id)
        except Exception as err:  # one bad thread must not stop the rest
            logger.info("finding resolution: resolving thread {} soft-failed: {}", thread_id, err)
            continue
        resolved += 1
    if resolved:
        logger.info(
            "resolved {} review thread(s) on PR #{} whose findings are gone from the new commits",
            resolved,
            pull_number,
        )
    return resolved


def _comments_to_findings(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map legacy inline comments to terminal-submission finding dicts."""
    findings: list[dict[str, Any]] = []
    for comment in comments:
        row: dict[str, Any] = {
            "path": comment["path"],
            "body": str(comment.get("body") or ""),
            "severity": "Major",
        }
        if "line" in comment:
            row["line"] = int(comment["line"])
        findings.append(row)
    return findings


def _legacy_params_to_submission(params: dict[str, Any]) -> dict[str, Any]:
    """Construct the VP1 submission shape from legacy review params (D7)."""
    approved = bool(params.get("approved"))
    request_changes = bool(params.get("request_changes"))
    body = str(params.get("body") or "")
    comments = list(params.get("comments") or [])

    if approved and request_changes:
        msg = "approved and request_changes are mutually exclusive"
        raise ValueError(msg)

    if approved:
        return {"verdict": "approve", "summary": body, "findings": []}
    if request_changes:
        return {
            "verdict": "request_changes",
            "summary": body or "Request changes",
            "findings": _comments_to_findings(comments),
        }
    if comments:
        return {
            "verdict": "request_changes",
            "summary": body or "Review findings",
            "findings": _comments_to_findings(comments),
        }
    return {"verdict": "approve", "summary": body, "findings": []}


async def _publish_github_review(ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    """Post a GitHub review after a validated terminal submission exists (V6)."""
    pull_number = int(params["pull_number"])
    approved = bool(params.get("approved"))
    request_changes = bool(params.get("request_changes"))
    submission = ctx.tool_state.terminal_submission
    if submission is not None:
        approved = submission.verdict == "approve"
        request_changes = submission.verdict == "request_changes"

    body = params.get("body")
    comments = list(params.get("comments") or [])

    primary = primary_repo_state(ctx.tool_state)
    primary.issue_number = pull_number

    event = "COMMENT"
    if approved and ctx.pr_approve_enabled and ctx.trust_tier == "trusted":
        event = "APPROVE"
    elif request_changes:
        event = "REQUEST_CHANGES"

    payload: dict[str, Any] = {"event": event}
    if body:
        await ensure_learnings_review_delta(ctx.tool_state)
        body_with_delta = merge_learnings_delta_into_review_body(ctx.tool_state, str(body))
        payload["body"] = add_footer(ctx, body_with_delta)
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
    _maybe_suggest_eval_add(ctx)
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
    resolved = await _resolve_fixed_finding_threads(
        ctx,
        pull_number=pull_number,
        posted_bodies=[str(item.get("body") or "") for item in inline],
    )
    if resolved:
        response["resolvedThreads"] = resolved
    return response


async def publish_pull_request_review(ctx: ToolContext) -> dict[str, Any]:
    """Publish the validated terminal submission to GitHub (internal, not an MCP tool)."""
    if ctx.tool_state.terminal_submission is None:
        msg = "no validated terminal submission available for publication"
        raise ValueError(msg)

    pending = ctx.tool_state.pending_review_publication
    if pending is None:
        submission = ctx.tool_state.terminal_submission
        primary = primary_repo_state(ctx.tool_state)
        pull_number = primary.issue_number or ctx.tool_state.pr_number
        if pull_number is None:
            msg = "no pull number available for validated terminal submission publication"
            raise ValueError(msg)
        pending = {
            "pull_number": pull_number,
            "body": submission.summary,
            "comments": [],
            "approved": submission.verdict == "approve",
            "request_changes": submission.verdict == "request_changes",
        }

    ctx.tool_state.review_phase = ReviewPhase.PUBLISH.value
    stamp_review_phase_on_active_span(ReviewPhase.PUBLISH)
    result = await _publish_github_review(ctx, pending)
    ctx.tool_state.review_phase = ReviewPhase.COMPLETE.value
    stamp_review_phase_on_active_span(ReviewPhase.COMPLETE)
    return result


def create_pull_request_review_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        pull_number = int(params["pull_number"])
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

        submission_payload = _legacy_params_to_submission(params)
        record_validated_terminal_submission(ctx, submission_payload)

        publication_params = dict(params)
        publication_params["pull_number"] = pull_number
        ctx.tool_state.pending_review_publication = publication_params

        ctx.tool_state.review_phase = ReviewPhase.PUBLISH.value
        stamp_review_phase_on_active_span(ReviewPhase.PUBLISH)
        result = await _publish_github_review(ctx, publication_params)
        ctx.tool_state.review_phase = ReviewPhase.COMPLETE.value
        stamp_review_phase_on_active_span(ReviewPhase.COMPLETE)
        return result

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
