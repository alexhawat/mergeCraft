"""Publish Action review evidence, status checks, and learnings."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.classify.triage import TriageDecision
from mergecraft.evidence.run_packet import emit_run_packet, resolve_prepared_run_packet
from mergecraft.findings.fix_brief import fix_brief_path
from mergecraft.run_outcome import (
    RUN_OUTCOME_CONCLUSION,
    CompletionConclusion,
    RunOutcome,
    outcome_with_disposition_ledger,
    run_succeeded_for_outcome,
)
from mergecraft.run_outcome import is_review_mode as _is_review_mode
from mergecraft.utils import gha_log
from mergecraft.utils.learnings import (
    persist_learnings,
)
from mergecraft.utils.status_checks import report_status_checks

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mergecraft.action.review_state import RunContext
    from mergecraft.evidence.packet import MergeEvidencePacket
    from mergecraft.evidence.shadow import VerdictProtocolPrediction
    from mergecraft.mcp.context import ToolContext
    from mergecraft.memory.feedback import FeedbackReport

from mergecraft.action.review_policy import _lite_completion_conclusion
from mergecraft.action.review_record import (
    _cost_summary,
    _token_summary,
    publish_deterministic_record,
)
from mergecraft.action.review_sinks import _scan_sinks_after_run
from mergecraft.action.review_state import MainResult


async def _report_record_publication_failure(
    tool_context: ToolContext, prepared: Any, sink_error: str | None
) -> None:
    """Post the checks for a run whose formal review record failed to publish."""
    await report_status_checks(
        tool_context,
        run_succeeded=False,
        failure_reason="formal review record publication failed",
        conclusion="neutral",
        packet=prepared,
        approval_failure_reason=sink_error,
    )


async def _publish(
    ctx: RunContext,
    *,
    outcome: RunOutcome,
    failure_reason: str | None,
    attrs_source: Callable[[], dict[str, Any]] | None = None,
    verdict_prediction: VerdictProtocolPrediction | None = None,
    actual_outcome: str | None = None,
    verdict_diagnostic: Any | None = None,
    emit: bool = True,
    upload_sarif: Callable[[ToolContext], Awaitable[object]],
    sink_scan_error: str | None = None,
    sink_scan: Callable[[Path | None], str | None] | None = None,
) -> str | None:
    """Prepare packet + emit + persist learnings + status checks.

    Shared by the normal post-agent path in ``_finalize`` and the exception
    cleanup path (``emit=False`` — failure still reports status but skips
    SARIF/packet emit). Tracer span wraps the emit path only.

    ``sink_scan_error`` (SX-D10) is the pre-publication sink-hit reason. It does
    not change the completion check — the caller has already mapped the failed
    outcome — but it forces the ``mergecraft-approval`` conclusion to
    ``failure`` regardless of the packet verdict, so a credential that reached a
    local sink cannot leave the merge gate open.

    ``sink_scan`` (SX-D10) is the post-emission scan callback. In the emit path
    the packet is written **before** the status/approval report, then
    ``sink_scan(written)`` re-scans it (the artifact the workflow uploads). A
    non-``None`` result forces the completion and approval checks to ``failure``
    for this report, so a credential that only ever reached the generated
    packet still closes the merge gate before artifact upload.
    """
    tool_context = ctx.tool_context
    if tool_context is None:
        return None
    prepared = resolve_prepared_run_packet(
        tool_context, run_succeeded=run_succeeded_for_outcome(outcome)
    )

    # Effective values the status report uses. The pre-emission scan may already
    # have failed the run; the post-emission scan (emit path) can update these
    # before the report is posted. An open analyzer disposition ledger makes a
    # passed run inconclusive so the completion check agrees with the packet's
    # ``neutral`` approval conclusion (#1014); ``_finalize`` applies the same
    # rule to the run's own result.
    effective_outcome, ledger_reason = outcome_with_disposition_ledger(outcome, prepared)
    effective_failure_reason = ledger_reason or failure_reason
    effective_sink_error = sink_scan_error

    async def publish_status() -> None:
        await _publish_learnings_and_status(
            tool_context,
            prepared=prepared,
            effective_outcome=effective_outcome,
            effective_failure_reason=effective_failure_reason,
            effective_sink_error=effective_sink_error,
            verdict_diagnostic=verdict_diagnostic,
            approval_withheld_reason=ctx.approval_withheld_reason,
            feedback_report=ctx.feedback_report,
        )

    if not emit:
        await publish_status()
        return None

    from mergecraft.tracing.tracer import get_tracer_from_settings

    if ctx.settings is None:
        msg = "settings is required when emit=True"
        raise ValueError(msg)
    if attrs_source is None:
        msg = "attrs_source is required when emit=True"
        raise ValueError(msg)
    tracer = get_tracer_from_settings(ctx.settings)
    with tracer.start_span("mergecraft.publish", attrs_source=attrs_source) as _span:
        # SX-D10 — emit *before* the status/approval report so the post-emission
        # scan can see the packet this run generates; the packet is an upload
        # source, and a credential that only ever reached it would otherwise
        # ship untouched. A hit is folded into the report below (completion and
        # approval both ``failure``) and the sink is already deleted.
        written = await asyncio.to_thread(
            emit_run_packet,
            tool_context,
            packet=prepared,
            verdict_prediction=verdict_prediction,
            actual_outcome=actual_outcome,
            completed_review=(
                effective_outcome is RunOutcome.passed
                and effective_sink_error is None
                and _is_review_mode(tool_context.tool_state.selected_mode)
            ),
        )
        if sink_scan is not None:
            post_error = sink_scan(Path(written) if written else None)
            if post_error is not None:
                effective_sink_error = post_error
                effective_outcome = RunOutcome.failed
                effective_failure_reason = post_error
        await publish_status()
        # #39 — opt-in, off by default, and never a gate: with `sarif_upload`
        # unset this returns before making any request.
        await upload_sarif(tool_context)
        return str(written) if written else None


async def _publish_policy_skip(ctx: RunContext, reason: str) -> MainResult:
    """Publish a head-bound record of a deliberate no-op and neutral checks."""
    tool_context = ctx.tool_context
    assert tool_context is not None
    from mergecraft.config.trust_policy import bound_head_sha
    from mergecraft.mcp.tool_state import primary_repo_state

    head_sha = bound_head_sha(
        ctx.gh_event or {}, event_name=os.environ.get("GITHUB_EVENT_NAME", "")
    )
    if not head_sha:
        return MainResult(
            success=False,
            error="Cannot record a review policy skip without a bound PR head.",
            outcome=RunOutcome.inconclusive,
        )
    primary_repo_state(tool_context.tool_state).checkout_sha = head_sha
    # Unavailable draft-lite work stays inconclusive and cannot use the
    # workflow exception for an explicit policy decision to run no review.
    triage = (
        TriageDecision(tier="skip", recognizer="reviewPolicy", reason=reason)
        if ctx.automatic_review == "skip"
        else TriageDecision(tier="lite", recognizer=None, reason=reason)
    )
    tool_context.tool_state.triage = triage

    sink_error = _scan_sinks_after_run(ctx)
    packet_path = None
    packet = None
    if sink_error is None:
        packet = resolve_prepared_run_packet(tool_context, run_succeeded=False)
        if (
            packet is not None
            and packet.decision is not None
            and packet.decision.verdict == "neutral"
            and packet.reviewed_head_sha == head_sha
        ):
            packet_path = await asyncio.to_thread(emit_run_packet, tool_context, packet=packet)
            if packet_path is not None:
                sink_error = _scan_sinks_after_run(
                    ctx, extra_paths=[packet_path, fix_brief_path(packet_path)]
                )

    if sink_error is not None or packet_path is None:
        error = sink_error or "Could not record the review policy skip in the evidence packet."
        await report_status_checks(
            tool_context,
            run_succeeded=False,
            conclusion="failure",
            failure_reason=error,
            approval_failure_reason=sink_error,
        )
        return MainResult(success=False, error=error, outcome=RunOutcome.failed)

    await report_status_checks(
        tool_context,
        run_succeeded=False,
        conclusion="neutral",
        failure_reason=reason,
        packet=packet,
    )
    logger.info("» {}", reason)
    return MainResult(
        success=True,
        output=reason,
        result=reason,
        outcome=RunOutcome.inconclusive,
        evidence_packet_path=str(packet_path),
    )


async def _publish_learnings_and_status(
    tool_context: ToolContext,
    *,
    prepared: MergeEvidencePacket | None,
    effective_outcome: RunOutcome,
    effective_failure_reason: str | None,
    effective_sink_error: str | None,
    verdict_diagnostic: Any | None,
    approval_withheld_reason: str | None,
    feedback_report: FeedbackReport | None,
) -> None:
    await persist_learnings(tool_context)
    pull_number = tool_context.tool_state.pr_number
    if pull_number is None and tool_context.payload.event.issue_number is not None:
        pull_number = int(tool_context.payload.event.issue_number)
    # A refused terminal verdict (scope, schema, semantic or policy) is
    # recorded on ``tool_state``; it names the actual cause, so it wins over
    # the generic run failure reason. This is deliberately not gated on
    # ``prepared.decision is None``: ``decide_approval`` always returns a
    # ``PacketDecision``, so that condition never holds and the reason never
    # reached the record — a refused run read as a clean one (plan 13 D5).
    rejection_reason = tool_context.tool_state.last_terminal_rejection
    if rejection_reason is None and tool_context.tool_state.finalize_failure:
        rejection_reason = tool_context.tool_state.finalize_failure
    review_run = tool_context.tool_state.selected_mode in {"Review", "IncrementalReview"}
    if rejection_reason is None and tool_context.tool_state.terminal_publication_failed:
        rejection_reason = "terminal_publication_failed"
    lite_run = tool_context.tool_state.lite_review is not None
    if (
        rejection_reason is None
        and review_run
        and tool_context.tool_state.terminal_submission is None
    ):
        # A lite run records no terminal verdict by design (one capped call, no
        # agent); only a real failure reason belongs in its record.
        rejection_reason = effective_failure_reason or (
            None if lite_run else "no_accepted_model_verdict"
        )
    # A refused terminal attempt owes the PR a record even when the agent never
    # selected a mode: without it a rejected approval left only a failing
    # approval check and no review naming the rejection (#1211).
    terminal_rejected = tool_context.tool_state.last_terminal_rejection is not None
    if (
        pull_number is not None
        and prepared is not None
        and (
            review_run
            or lite_run
            or terminal_rejected
            or tool_context.tool_state.review is not None
        )
    ):
        try:
            await publish_deterministic_record(
                pull_number=int(pull_number),
                packet=prepared,
                rejection_reason=rejection_reason,
                tmpdir=tool_context.tmpdir,
                ctx=tool_context,
                run_outcome=effective_outcome,
                verdict_diagnostic=verdict_diagnostic,
                approval_withheld_reason=approval_withheld_reason,
            )
        except Exception as err:
            if lite_run:
                # The lite comment is the record a human reads, but the checks carry
                # the same findings and the never-approve rule; a failed post is
                # reported, and the checks below still post.
                logger.warning(
                    "» the lite review comment could not be published ({}); the checks "
                    "still carry its findings",
                    type(err).__name__,
                )
                gha_log.warning("mergeCraft: the lite review comment could not be published")
            else:
                await _report_record_publication_failure(
                    tool_context, prepared, effective_sink_error
                )
                raise
    run_ok = run_succeeded_for_outcome(effective_outcome)
    completion: CompletionConclusion = RUN_OUTCOME_CONCLUSION[effective_outcome]
    completion_reason = effective_failure_reason
    lite_completion = _lite_completion_conclusion(
        tool_context.tool_state, prepared, outcome_conclusion=completion
    )
    if lite_completion is not None:
        completion, lite_reason = lite_completion
        completion_reason = completion_reason or lite_reason
    await report_status_checks(
        tool_context,
        run_succeeded=run_ok,
        failure_reason=completion_reason,
        conclusion=completion,
        packet=prepared,
        approval_failure_reason=effective_sink_error,
    )
    if prepared is not None:
        from mergecraft.utils.status_checks import _run_url
        from mergecraft.utils.step_summary import append_step_summary, render_step_summary

        submission = tool_context.tool_state.terminal_submission
        analyzer_run = tool_context.tool_state.analyzer_run
        outcome_label = (
            "no_verdict" if prepared.decision is None else ("success" if run_ok else "failure")
        )
        summary_body = render_step_summary(
            packet=prepared,
            outcome_label=outcome_label,
            rejection_reason=rejection_reason,
            run_url=_run_url(tool_context),
            run_outcome=effective_outcome,
            verdict_diagnostic=verdict_diagnostic,
            analyzer_summary=analyzer_run.pre_merge_summary if analyzer_run is not None else None,
            agent_summary=submission.summary if submission is not None else None,
            trust_tier=tool_context.trust_tier,
            token_summary=_token_summary(
                tool_context.tool_state.usage_entries,
                budget_tracker=tool_context.budget_tracker,
            ),
            cost_summary=_cost_summary(
                tool_context.tool_state.usage_entries,
                budget_tracker=tool_context.budget_tracker,
            ),
            llm_review_timing=tool_context.tool_state.llm_review_timing,
            credential_degradations=list(tool_context.tool_state.credential_degradations),
            feedback_report=feedback_report if effective_sink_error is None else None,
        )
        append_step_summary(summary_body)
