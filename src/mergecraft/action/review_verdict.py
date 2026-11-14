"""Publish an Action verdict and withdraw invalid approvals."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.run_outcome import is_review_mode as _is_review_mode

if TYPE_CHECKING:
    from mergecraft.action.review_state import RunContext
    from mergecraft.agents.shared import AgentResult
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.tool_state import (
        ToolState,
    )


_ORCHESTRATOR_PUBLISH_STEP = "orchestrator.publish_review"


def owes_a_terminal_review(tool_state: ToolState) -> bool:
    """Whether this run recorded a verdict that GitHub is owed.

    A run that recorded no submission owes nothing: it records no publish step
    and says nothing. Everything past this point is about a verdict that exists.
    """
    return tool_state.terminal_submission is not None


def publication_skip_reason(
    tool_state: ToolState,
    agent_result: AgentResult,
    *,
    verdict_protocol: str | None,
) -> str | None:
    """Why this run will not publish its recorded verdict, or ``None`` when it will.

    Call only when :func:`owes_a_terminal_review` is true; a run that recorded
    nothing returns before this and records nothing. A recorded verdict that
    stops short of a review must name itself: #1017's Codex rung recorded
    ``request_changes``, published no review, and recorded nothing about why, so
    the only visible trace was the failing ``mergecraft-approval`` check. The
    three ways it happens are the shadow protocol, a run that is not a review
    run, and a submission that the post-run re-validation rejected — the last one
    is what to look for first when a review is expected and absent.
    """
    if getattr(tool_state, "review_publication_sticky_only", False):
        return (
            "this non-terminal rung deferred its neutral verdict to the fallback "
            "rung; the run record is in the sticky progress comment (#1078)"
        )
    if verdict_protocol == "shadow":
        return "the verdict protocol is shadow, so the verdict is recorded but not published"
    if not _is_review_mode(tool_state.selected_mode):
        return (
            "the run is not a review run "
            f"(selected_mode={tool_state.selected_mode!r}), so it publishes no review"
        )
    if not agent_result.terminal_submission_received:
        rejection = str((agent_result.diagnostics or {}).get("rejection_reason") or "unknown")
        return f"the recorded submission was rejected at post-run validation ({rejection})"
    return None


def _approve_event_eligible(tool_context: ToolContext) -> bool:
    """Whether an ``approve`` verdict on this run is posted as a GitHub APPROVE.

    Mirrors the publisher's event rule: approvals enabled, trusted authority,
    and a run that had something in review scope (a triage skip never approves).
    """
    triage_skipped = getattr(tool_context.tool_state.triage, "tier", None) == "skip"
    return (
        bool(tool_context.pr_approve_enabled)
        and tool_context.authority_trust == "trusted"
        and not triage_skipped
    )


async def _publish_recorded_verdict(
    tool_context: ToolContext,
    agent_result: AgentResult,
    *,
    verdict_protocol: str | None,
    approval_withheld: str | None = None,
) -> None:
    """Phase 4 — publish the accepted terminal submission once (the run owns publication).

    A compliant Review run records one ``submit_review_verdict`` and publishes
    nothing itself; the run publishes the final attempt's accepted verdict
    here, before the outcome is classified. The publisher is idempotent on its
    receipt: an agent-published review with the same verdict is not posted
    again, and a receipt for a different verdict posts nothing and sets the
    mismatch flag. A failure never escapes Phase 4; the classifier reads the
    missing receipt (or ``terminal_publication_failed``) instead. The step is
    recorded in the trajectory as ``orchestrator.publish_review``, ``ok`` only
    when a receipt for the recorded verdict exists, including when the agent
    already published it. The row carries the receipt's ``payload_hash`` and
    the recorded findings GitHub's inline view lacks.

    A run that recorded no verdict records no step. A recorded verdict the run
    does not publish (:func:`publication_skip_reason`) is recorded as a not-ok
    step stamped ``failure_class="declined"`` with the reason in ``error``, so
    the trajectory auditor reads it as a decision, not a failed call.

    ``approval_withheld`` is the reason the run's outcome would not be
    ``passed`` (resolved before publication). When it is set, an ``approve``
    verdict is published as a ``COMMENT`` review rather than an ``APPROVE``:
    a run that does not pass never leaves an approval on the pull request.
    """
    tool_state = tool_context.tool_state
    if not owes_a_terminal_review(tool_state):
        # Nothing was recorded, so the run owes GitHub nothing and says nothing.
        return
    skip_reason = publication_skip_reason(
        tool_state,
        agent_result,
        verdict_protocol=verdict_protocol,
    )
    if skip_reason is not None:
        # A recorded verdict that reaches no review is evidence about the run, not
        # a silent return: the packet's trajectory is where a missing review is
        # explained, and #1017's Codex rung is what its absence looks like.
        logger.warning("» the run did not publish the recorded review verdict: {}", skip_reason)
        from mergecraft.evidence.trajectory import record_tool_call

        record_tool_call(
            tool_state,
            tool=_ORCHESTRATOR_PUBLISH_STEP,
            arguments=None,
            ok=False,
            error=skip_reason,
            failure_class="declined",
        )
        return
    from mergecraft.evidence.trajectory import record_tool_call
    from mergecraft.mcp.review import publish_pull_request_review

    submission = tool_state.terminal_submission
    withhold = (
        approval_withheld is not None
        and submission is not None
        and submission.verdict == "approve"
        and _approve_event_eligible(tool_context)
    )
    approve_enabled = tool_context.pr_approve_enabled
    if withhold:
        logger.warning(
            "» the approve verdict is published as a comment, not an approval: {}",
            approval_withheld,
        )
        tool_context.pr_approve_enabled = False
    try:
        publish_started = time.perf_counter()
        response = await publish_pull_request_review(
            tool_context, run_not_passing_reason=approval_withheld
        )
        tool_state.phase_elapsed_s["publish"] = round(time.perf_counter() - publish_started, 3)
    except Exception as exc:
        logger.warning("» the run could not publish the recorded review verdict: {}", exc)
        record_tool_call(
            tool_state,
            tool=_ORCHESTRATOR_PUBLISH_STEP,
            arguments=None,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )
        return
    finally:
        tool_context.pr_approve_enabled = approve_enabled
    # A same-verdict skip (the agent already published this verdict) is
    # recorded too: the receipt is present, and this row is where its hash and
    # any inline gap are read. A skipped *mismatch* (``success: false``) is
    # recorded as not ok.
    receipt = tool_state.review
    published = response.get("success") is True and receipt is not None
    record_tool_call(
        tool_state,
        tool=_ORCHESTRATOR_PUBLISH_STEP,
        arguments=None,
        ok=published,
        error=None if published else str(response.get("reason") or "no receipt"),
        payload_hash=receipt.payload_hash if receipt is not None else None,
        publication_incomplete=list(tool_state.publication_incomplete) if published else None,
    )


async def _dismiss_unpassed_approval(
    ctx: RunContext,
    *,
    reason: str,
    review_before_publication: Any,
) -> bool:
    """Dismiss this run's APPROVE review when the run did not pass; return whether it did.

    The formal review is published with an APPROVE only when every gate known
    before publication passed, but some inputs resolve only afterwards (the
    disposition ledger, the post-emission sink scan, a publication mismatch),
    and an agent can publish mid-run. When the final outcome is not ``passed``
    and the review this run holds was posted as an APPROVE, it is dismissed
    with the reason, so the pull request never keeps an approval from a run
    that did not pass. Total: a failed dismissal is logged and recorded in the
    trajectory, never raised.
    """
    tool_context = ctx.tool_context
    if tool_context is None:
        return False
    tool_state = tool_context.tool_state
    review = tool_state.review
    if review is None or review.verdict != "approve" or review.reviewed_sha is None:
        return False
    if not _approve_event_eligible(tool_context):
        return False
    if review is not review_before_publication and ctx.approval_withheld_reason is not None:
        # Published at finalize as a comment: there is no approval to dismiss.
        return False
    pull_number = tool_state.pr_number
    if pull_number is None and tool_context.payload.event.issue_number is not None:
        pull_number = int(tool_context.payload.event.issue_number)
    if pull_number is None:
        return False
    from mergecraft.evidence.trajectory import record_tool_call

    owner, repo = tool_context.repo.owner, tool_context.repo.name
    message = f"mergeCraft: this run did not pass, so its approval is withdrawn — {reason}"
    try:
        await tool_context.scm.put(
            f"/repos/{owner}/{repo}/pulls/{int(pull_number)}/reviews/{review.id}/dismissals",
            json={"message": message[:1000], "event": "DISMISS"},
        )
    except Exception as exc:  # dismissal is best effort; the checks already fail closed
        logger.warning("» could not dismiss this run's approval review {}: {}", review.id, exc)
        record_tool_call(
            tool_state,
            tool="orchestrator.dismiss_approval",
            arguments=None,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )
        return False
    logger.warning("» dismissed this run's approval review {}: {}", review.id, reason)
    record_tool_call(tool_state, tool="orchestrator.dismiss_approval", arguments=None, ok=True)
    return True
