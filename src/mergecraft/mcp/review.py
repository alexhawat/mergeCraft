"""Register the legacy review tool and adapt its inputs to terminal submissions.

Module: mergecraft.mcp.review
Depends: mergecraft.mcp.{review_body,review_publish,shared,verdict}

Exports:
    Functions:
        create_pull_request_review_tool — Build the MCP tool for posting a review.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.mcp.review_body import (
    format_analyzer_inline_body,
    merge_deterministic_preamble_into_review_body,
)
from mergecraft.mcp.review_publish import (
    ANCHOR_RECOVERY_RETRY_CEILING,
    REVIEW_BODY_MAX_CHARS,
    PublicationScopeError,
    assert_publication_scope,
    bound_commit_id,
    existing_publication_response,
    publish_github_review,
    publish_pull_request_review,
    reject_mismatched_publication,
    resolve_bound_commit_id,
    resolve_bound_pull_number,
    should_publish_sticky_only,
)
from mergecraft.mcp.review_publish import (
    create_github_review_with_anchor_recovery as _create_github_review_with_anchor_recovery,
)
from mergecraft.mcp.review_publish import (
    publish_github_review as _publish_github_review,
)
from mergecraft.mcp.review_publish import (
    recover_review_after_lost_receipt as _recover_review_after_lost_receipt,
)
from mergecraft.mcp.review_publish import (
    recovered_receipt as _recovered_receipt,
)
from mergecraft.mcp.review_publish import (
    recovered_review_inline_comments as _recovered_review_inline_comments,
)
from mergecraft.mcp.review_publish import (
    recovered_review_verdict as _recovered_review_verdict,
)
from mergecraft.mcp.review_publish import (
    truncate_review_body_for_github as _truncate_review_body_for_github,
)
from mergecraft.mcp.shared import ToolClass, execute, tool
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.mcp.verdict import (
    REJECTION_REQUEST_CHANGES_NO_FINDINGS,
    ReviewPhase,
    after_terminal_submission_recorded,
    ensure_review_scope_for_terminal,
    record_validated_terminal_submission,
    recorded_submission_payload,
    revalidate_recorded_submission,
    validate_submission,
    validation_state_from_tool_context,
)
from mergecraft.review_taxonomy import finding_fingerprint

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.shared import ToolSpec

__all__ = [
    "ANCHOR_RECOVERY_RETRY_CEILING",
    "REVIEW_BODY_MAX_CHARS",
    "PublicationScopeError",
    # Compatibility for callers of the former publication helpers.
    "_create_github_review_with_anchor_recovery",
    "_publish_github_review",
    "_recover_review_after_lost_receipt",
    "_recovered_receipt",
    "_recovered_review_inline_comments",
    "_recovered_review_verdict",
    "_truncate_review_body_for_github",
    "create_pull_request_review_tool",
    "format_analyzer_inline_body",
    "merge_deterministic_preamble_into_review_body",
    "publish_pull_request_review",
    "should_publish_sticky_only",
]


def _comments_to_findings(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map legacy inline comments to terminal-submission finding dicts."""
    findings: list[dict[str, Any]] = []
    for comment in comments:
        path = str(comment["path"])
        body = str(comment.get("body") or "")
        row: dict[str, Any] = {
            "path": path,
            "body": body,
            "severity": "Major",
        }
        if path and body:
            row["fingerprint"] = finding_fingerprint(path=path, body=body)
        if "line" in comment:
            row["line"] = int(comment["line"])
        findings.append(row)
    return findings


def _legacy_params_to_submission(params: dict[str, Any]) -> dict[str, Any] | None:
    """Map ``create_pull_request_review`` params onto the terminal-verdict shape.

    A plain COMMENT (no ``approved`` / ``request_changes`` and no inline
    comments) is not a terminal verdict. Explicit ``approved: false`` must
    not fall through to ``approve``. ``request_changes`` with no findings
    is left empty so ``validate_submission`` can apply D9 rather than
    fabricating a ``path="."`` row.
    """
    approved = bool(params.get("approved"))
    request_changes = bool(params.get("request_changes"))
    body = str(params.get("body") or "")
    comments = list(params.get("comments") or [])

    if approved and request_changes:
        msg = "approved and request_changes are mutually exclusive"
        raise ValueError(msg)

    if approved:
        return {"verdict": "approve", "summary": body or "Approve", "findings": []}
    findings = _comments_to_findings(comments)
    if request_changes:
        return {
            "verdict": "request_changes",
            "summary": body or "Request changes",
            "findings": findings,
        }
    if findings:
        return {
            "verdict": "request_changes",
            "summary": body or "Review findings",
            "findings": findings,
        }
    if "approved" in params:
        return {
            "verdict": "request_changes",
            "summary": body or "Review comment",
            "findings": [],
        }
    return None


def _maybe_revalidate_before_publish(ctx: ToolContext) -> None:
    """Re-run terminal validation before publish unless already graded at submit."""
    submission = ctx.tool_state.terminal_submission
    if submission is None:
        return
    if ctx.tool_state.review_phase == ReviewPhase.SUBMIT.value:
        validation = validate_submission(
            recorded_submission_payload(submission),
            state=validation_state_from_tool_context(ctx),
        )
        # ``request_changes_without_findings`` is rejected at record time; this
        # branch is a legacy escape hatch when phase is still SUBMIT and the
        # stored payload would fail re-validation for that reason only.
        if (
            not validation.accepted
            and validation.rejection_reason == REJECTION_REQUEST_CHANGES_NO_FINDINGS
        ):
            return
    revalidate_recorded_submission(ctx)


def create_pull_request_review_tool(ctx: ToolContext) -> ToolSpec:
    """Build the MCP review tool with the legacy submission adapter."""

    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        from mergecraft.analyzers.trust_posture import trust_posture_from_tool_state

        posture = trust_posture_from_tool_state(
            ctx.tool_state,
            analyzers_mode=getattr(ctx, "analyzers_mode", None),
            execution_trust=ctx.trust_tier,
            authority_trust=ctx.authority_trust,
        )
        if bool(params.get("approved")) and not posture.may_approve_on_github():
            msg = (
                "APPROVE is not permitted on this run: authority trust is untrusted "
                "(trust.selfReview must be full with explicit operator confirmation)"
            )
            raise ValueError(msg)

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

        pull_number = resolve_bound_pull_number(ctx, params)
        commit_id = resolve_bound_commit_id(ctx, params)
        assert_publication_scope(ctx, pull_number=pull_number, commit_id=commit_id)

        primary = primary_repo_state(ctx.tool_state)
        primary.issue_number = pull_number

        existing = existing_publication_response(
            ctx,
            pull_number=pull_number,
            commit_id=commit_id,
        )
        if existing is not None:
            ctx.tool_state.review_publication_entrypoint = "create_pull_request_review"
            if existing.get("publicationMismatch"):
                # The agent must see that its verdict did not reach GitHub.
                raise ValueError(str(existing["reason"]))
            return existing

        ensure_review_scope_for_terminal(ctx.tool_state, "create_pull_request_review")

        if ctx.tool_state.terminal_submission is None:
            submission_payload = _legacy_params_to_submission(params)
            if submission_payload is not None:
                recorded = record_validated_terminal_submission(ctx, submission_payload)
                after_terminal_submission_recorded(ctx, recorded, replayed=False)
        else:
            reject_mismatched_publication(ctx.tool_state.terminal_submission, params)
            _maybe_revalidate_before_publish(ctx)

        publication_params = dict(params)
        publication_params["pull_number"] = pull_number
        bound_commit = bound_commit_id(ctx)
        if bound_commit:
            publication_params["commit_id"] = bound_commit
        submission = ctx.tool_state.terminal_submission
        if submission is not None:
            publication_params["body"] = submission.summary
        ctx.tool_state.pending_review_publication = publication_params

        from mergecraft.mcp.review_phase_machine import advance_review_phase

        advance_review_phase(ctx.tool_state, ReviewPhase.PUBLISH)
        from mergecraft.mcp.verification import emit_published_findings

        emit_published_findings(ctx)
        result = await publish_github_review(
            ctx,
            publication_params,
            entrypoint="create_pull_request_review",
        )
        advance_review_phase(ctx.tool_state, ReviewPhase.COMPLETE)
        return result

    return tool(
        name="create_pull_request_review",
        tool_class=ToolClass.REVIEW_WRITE,
        mutates=True,
        description=(
            "Submit a review for an existing pull request. "
            "Set approved:true to approve, request_changes:true to block, or neither "
            "for a plain comment review."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body": {"type": "string"},
                "approved": {"type": "boolean"},
                "request_changes": {"type": "boolean"},
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
            "required": [],
            "additionalProperties": False,
        },
        execute=execute(_run, "create_pull_request_review"),
    )
