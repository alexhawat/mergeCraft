"""Revalidate completed Action reviews and resolve their final outcome."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.agents.post_run import finalize_agent_result
from mergecraft.agents.shared import FAILOVER_ELIGIBLE_KEY, AgentResult
from mergecraft.findings.fix_brief import fix_brief_path
from mergecraft.main_outcome import (
    _publication_outcome_inputs,
    _publication_unproven,
    _publish_span_attrs,
    _verdict_protocol_publish,
)
from mergecraft.prep.types import is_prep_install_failure
from mergecraft.run_outcome import (
    RunOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mergecraft.action.review_state import RunContext
    from mergecraft.config.settings import RepoSettings
    from mergecraft.evidence.shadow import VerdictProtocolPrediction
    from mergecraft.main_outcome import VerdictProtocolPublish
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.tool_state import (
        ReviewRecord,
        ToolState,
    )
    from mergecraft.mcp.verdict import VerdictDiagnostic

from typing import Protocol

from mergecraft.action.review_policy import _lite_inconclusive_reason
from mergecraft.action.review_sinks import _scan_sinks_after_run
from mergecraft.action.review_state import LiteAgentReview, MainResult, SkipAgentReview
from mergecraft.action.review_verdict import (
    _approve_event_eligible,
    _dismiss_unpassed_approval,
    _publish_recorded_verdict,
)
from mergecraft.review.outcome_resolution import OutcomeInputs, approval_withheld_reason
from mergecraft.review.pipeline.finalize import complete_outcome_inputs, finalize_review_outcome

_PREP_PUBLISH_WAIT_S: float = 30.0
"""How long publication waits for a still-running dependency install.

A fraction of the publish stage's budget: an install that has not finished by
the time the review did is stopped rather than allowed to hold publication
(and the evidence packet) until the stage times out.
"""


async def _await_prep(promise: Any) -> object:
    return await promise


async def _prep_failure_reason(
    tool_context: ToolContext, *, wait_s: float | None = None
) -> str | None:
    """Return a reason string when review-relevant dependency prep failed (W6.1).

    Awaits an in-progress install before inspecting status, for at most
    ``wait_s`` seconds (``None`` waits until the install's own deadline). An
    install still running then is stopped (its process groups are killed) and
    reported as a reason, so the run is ``inconclusive``: the review ran
    without its dependencies.

    Trusted-tier ``setup_script`` failures are **not** included here. They
    resolve through ``setup_failure_policy`` (S1 / D10 — closed vocabulary
    ``inconclusive`` | ``fail`` | ``warn``) at the post-run outcome block
    in :func:`main` — see :data:`mergecraft.action.inputs.SetupFailurePolicy`
    and ``docs/config-failure-policy.md``. This helper only emits a reason
    string; the ``fail`` policy short-circuits at the run-time guard above
    (so this branch never sees a ``fail``-mapped outcome). The ``warn`` and
    ``inconclusive`` policies carry their own resolution text via
    ``tool_state.setup_hook_failure`` and are deliberately kept off this
    helper's path so prep and setup failure reasons stay distinguishable
    to the operator.
    """
    state = tool_context.tool_state.dependency_installation
    if state is None:
        return None
    if state.status == "in_progress" and state.promise is not None:
        try:
            await asyncio.wait_for(_await_prep(state.promise), timeout=wait_s)
        except TimeoutError:
            cancel = getattr(state.promise, "cancel", None)
            if callable(cancel):
                cancel()
            return (
                f"dependency installation was still running {wait_s:g}s after the review "
                "finished and was stopped"
            )
        except Exception as exc:
            return f"dependency installation failed: {exc}"
    if state.status != "failed":
        return None
    reasons: list[str] = []
    for result in state.results or []:
        if is_prep_install_failure(result):
            reasons.extend(str(item) for item in result.issues)
    if reasons:
        return "; ".join(reasons)
    return "dependency installation failed"


def _coverage_gate_reason(tool_context: ToolContext, settings: RepoSettings) -> str | None:
    """Return the outcome reason when changed-line coverage is incomplete and gated.

    Total: a failure to account for coverage must not fail the run it describes, so it
    logs and reports no gate (the packet then simply carries no coverage section).
    """
    from mergecraft.evidence.coverage import (
        coverage_gate_reason,
        coverage_policy,
        coverage_section_for_state,
    )

    # A hard diff budget cannot be relaxed by the advisory coverage policy.
    if tool_context.tool_state.diff_budget_reason:
        return tool_context.tool_state.diff_budget_reason
    try:
        return coverage_gate_reason(
            coverage_section_for_state(tool_context.tool_state),
            on_incomplete=coverage_policy(tool_context, fallback=settings),
        )
    except Exception as exc:  # accounting is evidence, never a new way to crash a run
        logger.warning("changed-line coverage could not be accounted for: {}", exc)
        return None


async def _finalize(
    ctx: RunContext,
    result: AgentResult | SkipAgentReview | LiteAgentReview,
    *,
    publish_result: _PublishResult,
) -> MainResult:
    """Phase 4 — post-run, publish, outcome mapping (G4.2)."""
    assert ctx.tool_context is not None
    assert ctx.tool_state is not None
    assert ctx.settings is not None

    tool_context = ctx.tool_context
    tool_state = ctx.tool_state
    settings = ctx.settings
    ctx.publish_started = True

    lite = result if isinstance(result, LiteAgentReview) else None
    agent_result, finalize_failure = await _finalize_agent(ctx, result)
    # SX-D10 / F2=A — post-run sink scan of the run temp dir *and* every
    # artifact source the evidence uploads read. It runs after the agent
    # finished (``finalize_agent_result`` above), before the formal review is
    # published and the outcome is classified, and before the ``finally``
    # block's ``cleanup_temp_directory()`` would remove the sinks. A hit means
    # the credential already left the agent's process, so the response is to
    # stop the run, name the sink path — never its contents — force the
    # approval conclusion to ``failure`` and delete the sink before artifact
    # upload.
    #
    # This scan sees only what exists *before* publication; ``_publish`` emits
    # the packet afterwards, so it is re-scanned post-emission (below) before
    # the approval/status report and the workflow's upload.
    sink_scan_error: str | None = _scan_sinks_after_run(ctx)

    outcome_inputs = await _action_outcome_inputs(
        ctx,
        agent_result,
        lite=lite,
        finalize_failure=finalize_failure,
        sink_scan_error=sink_scan_error,
    )
    finalized = await _resolve_action_outcome(ctx, result=result, inputs=outcome_inputs)
    outcome = finalized.outcome
    failure_reason = finalized.failure_reason
    verdict_diagnostic_code = finalized.verdict_publish.diagnostic
    verdict_prediction = finalized.verdict_publish.prediction
    diagnostic_attrs = finalized.verdict_publish.attrs

    selected_mode_obj = next(
        (m for m in tool_context.modes if m.name == tool_context.tool_state.selected_mode),
        None,
    )

    # SX-D10 — the pre-publication scan above cannot see the packet ``_publish``
    # emits, and the workflow uploads that artifact. ``_publish`` re-scans it
    # after emission and before the status/approval report; the callback records
    # a post-emission hit here so this run's own result agrees with the checks
    # ``_publish`` posted.
    post_emission_sink: list[str] = []

    def _scan_emitted_sink(written: Path | None) -> str | None:
        extra = [written, fix_brief_path(written)] if written is not None else []
        post_error = _scan_sinks_after_run(ctx, extra_paths=extra)
        if post_error is not None:
            post_emission_sink.append(post_error)
        return post_error

    packet_path = await publish_result(
        ctx,
        outcome=outcome,
        failure_reason=failure_reason,
        attrs_source=lambda: _publish_span_attrs(outcome, selected_mode_obj) | diagnostic_attrs,
        verdict_prediction=verdict_prediction,
        actual_outcome=str(outcome) if verdict_prediction is not None else None,
        verdict_diagnostic=verdict_diagnostic_code,
        sink_scan_error=sink_scan_error,
        sink_scan=_scan_emitted_sink,
    )
    if post_emission_sink:
        # The emitted packet held credential material and has been deleted; the
        # completion and approval checks were already forced to ``failure``.
        outcome = RunOutcome.failed
        failure_reason = post_emission_sink[0]
    # #1014 — the same open-ledger rule ``_publish`` applied to the checks, so
    # this run's own result agrees with the completion check it posted.
    from mergecraft.review.outcome_resolution import finalize_run_outcome

    outcome, ledger_reason = finalize_run_outcome(outcome, tool_state.prepared_run_packet)
    failure_reason = ledger_reason or failure_reason
    if outcome is not RunOutcome.passed:
        await _dismiss_unpassed_approval(
            ctx,
            reason=failure_reason or f"the run outcome is {outcome.value}",
            review_before_publication=finalized.review_before_publication,
        )

    _record_final_verdict(tool_state, settings, agent_result, outcome)

    if outcome is not RunOutcome.passed:
        return MainResult(
            success=False,
            error=failure_reason or agent_result.error or "agent execution failed",
            evidence_packet_path=packet_path,
            outcome=outcome,
            verdict_diagnostic=verdict_diagnostic_code,
            failover_eligible=(
                not agent_result.success
                and (agent_result.metadata or {}).get(FAILOVER_ELIGIBLE_KEY) is True
            ),
        )

    output = tool_state.output or agent_result.output
    return MainResult(
        success=True,
        output=output,
        result=output,
        evidence_packet_path=packet_path,
        outcome=outcome,
        verdict_diagnostic=verdict_diagnostic_code,
    )


@dataclass(frozen=True, slots=True)
class _FinalizedActionReview:
    outcome: RunOutcome
    failure_reason: str | None
    verdict_publish: VerdictProtocolPublish
    review_before_publication: ReviewRecord | None


class _PublishResult(Protocol):
    async def __call__(
        self,
        ctx: RunContext,
        *,
        outcome: RunOutcome,
        failure_reason: str | None,
        attrs_source: Callable[[], dict[str, Any]],
        verdict_prediction: VerdictProtocolPrediction | None,
        actual_outcome: str | None,
        verdict_diagnostic: VerdictDiagnostic | None,
        sink_scan_error: str | None,
        sink_scan: Callable[[Path | None], str | None],
    ) -> str | None: ...


async def _finalize_agent(
    ctx: RunContext, result: AgentResult | SkipAgentReview | LiteAgentReview
) -> tuple[AgentResult, str | None]:
    assert ctx.tool_context is not None
    assert ctx.tool_state is not None
    tool_context = ctx.tool_context
    tool_state = ctx.tool_state
    finalize_failure: str | None = None
    if isinstance(result, (SkipAgentReview, LiteAgentReview)):
        agent_result = AgentResult(success=True)
    else:
        agent_result = result
        from mergecraft.mcp.verdict import fold_reviewer_dispatch_findings_into_submission

        # Secondary reviewers and file groups ran after the primary recorded its
        # verdict; their findings join it before it is re-validated and published.
        fold_reviewer_dispatch_findings_into_submission(tool_context)
        # A primary that published mid-run assembled (and cached) the evidence
        # packet before the fan-out and the roster recorded their findings.
        # Drop that snapshot so publication, the approval decision, the checks
        # and the emitted packet are all built from the complete run.
        tool_state.prepared_run_packet = None
        if ctx.run_ctx is not None:
            try:
                agent_result = await finalize_agent_result(ctx.run_ctx, agent_result)
            except Exception as exc:  # finalize validates arbitrary recorded state
                # ``finalize_agent_result`` re-validates the recorded submission, which
                # can raise whatever that state makes it raise, so the catch stays broad
                # but is never silent: the run cannot confirm its terminal verdict, so the
                # verdict is not published as one and the run is ``inconclusive``.
                finalize_failure = f"finalize_failed: {type(exc).__name__}"
                tool_state.finalize_failure = finalize_failure
                logger.warning(
                    "» post-run finalize failed ({}): {}; the run cannot confirm its "
                    "terminal verdict and fails closed",
                    type(exc).__name__,
                    exc,
                )
                # A driver result is already finalized (``received=True``), so the
                # unconfirmed verdict is withdrawn from publication explicitly.
                agent_result = replace(
                    agent_result,
                    terminal_submission_received=False,
                    diagnostics={
                        **(agent_result.diagnostics or {}),
                        "rejection_reason": finalize_failure,
                    },
                )

    return agent_result, finalize_failure


async def _action_outcome_inputs(
    ctx: RunContext,
    agent_result: AgentResult,
    *,
    lite: LiteAgentReview | None,
    finalize_failure: str | None,
    sink_scan_error: str | None,
) -> OutcomeInputs:
    assert ctx.tool_context is not None
    assert ctx.tool_state is not None
    assert ctx.settings is not None
    tool_context, tool_state, settings = ctx.tool_context, ctx.tool_state, ctx.settings
    # Every run-level gate is resolved before the formal review is published:
    # one shared resolver (``review.outcome_resolution``) maps them, and an
    # ``approve`` verdict is posted as an APPROVE only when the run passes.
    prep_reason = await _prep_failure_reason(tool_context, wait_s=_PREP_PUBLISH_WAIT_S)
    if ctx.budget_tracker is not None:
        ctx.run_bounds = ctx.budget_tracker.bounds
    inputs = OutcomeInputs(
        result=agent_result,
        # A lite run owes no terminal verdict and delivers no checkout coverage:
        # it is classified on its own reason below, not as a review-mode run.
        mode=None if lite is not None else tool_state.selected_mode,
        verdict_protocol=settings.gates.terminal_verdict,
        setup_reason=tool_state.setup_hook_failure or "",
        setup_policy=settings.setup_failure_policy,
        prep_reason=prep_reason,
        final_summary_written=tool_state.final_summary_written,
        coverage_incomplete_reason=_coverage_gate_reason(tool_context, settings),
        diff_budget_reason=tool_state.diff_budget_reason,
        terminal_rejection=tool_state.last_terminal_rejection,
        budget_exhaustion=ctx.budget_exhaustion,
        finalize_failure=finalize_failure,
        lite_reason=_lite_inconclusive_reason(lite.outcome) if lite is not None else None,
        sink_scan_error=sink_scan_error,
        structured_output_error=ctx.structured_output_error,
    )
    return complete_outcome_inputs(inputs, budget_tracker=ctx.budget_tracker)


async def _resolve_action_outcome(
    ctx: RunContext,
    *,
    result: AgentResult | SkipAgentReview | LiteAgentReview,
    inputs: OutcomeInputs,
) -> _FinalizedActionReview:
    assert ctx.tool_context is not None
    assert ctx.tool_state is not None
    assert ctx.settings is not None
    tool_context, tool_state, settings = ctx.tool_context, ctx.tool_state, ctx.settings
    agent_result = inputs.result
    review_before_publication = tool_state.review
    if not isinstance(result, (SkipAgentReview, LiteAgentReview)):
        withheld = approval_withheld_reason(inputs)
        if (
            withheld is not None
            and tool_state.terminal_submission is not None
            and tool_state.terminal_submission.verdict == "approve"
            and _approve_event_eligible(tool_context)
        ):
            ctx.approval_withheld_reason = withheld
        await _publish_recorded_verdict(
            tool_context,
            agent_result,
            verdict_protocol=settings.gates.terminal_verdict,
            approval_withheld=withheld,
        )
    publication_receipt, publication_mismatch = _publication_outcome_inputs(
        tool_state,
        result=agent_result,
        verdict_protocol=settings.gates.terminal_verdict,
    )
    resolution = finalize_review_outcome(
        replace(
            inputs,
            terminal_publication_failed=tool_state.terminal_publication_failed,
            terminal_publication_receipt=publication_receipt,
            terminal_publication_mismatch=publication_mismatch,
            terminal_publication_unproven=_publication_unproven(tool_state),
        )
    )
    verdict_publish = _verdict_protocol_publish(
        result=agent_result,
        mode=tool_state.selected_mode,
        setup_reason=inputs.setup_reason,
        setup_policy=settings.setup_failure_policy,
        prep_reason=inputs.prep_reason,
        final_summary_written=tool_state.final_summary_written,
        terminal_verdict=settings.gates.terminal_verdict,
        terminal_publication_failed=tool_state.terminal_publication_failed,
        terminal_publication_receipt=publication_receipt,
        terminal_publication_mismatch=publication_mismatch,
        terminal_rejection=tool_state.last_terminal_rejection,
    )
    return _FinalizedActionReview(
        resolution.outcome, resolution.failure_reason, verdict_publish, review_before_publication
    )


def _record_final_verdict(
    tool_state: ToolState, settings: RepoSettings, agent_result: AgentResult, outcome: RunOutcome
) -> None:
    # O9 (OB4) — the verdict span at the publish convergence point. Emitted
    # only when the agent actually submitted a terminal verdict: a run that
    # never submitted has no verdict, and the missing span is the signal
    # (the same diagnostic philosophy as the phase spans). The disagreement
    # flag is derived by the emitter, never supplied here.
    submission = tool_state.terminal_submission
    if submission is not None:
        try:
            from mergecraft.tracing import get_tracer_from_settings
            from mergecraft.tracing.signals import emit_verdict

            fallback_reason = (agent_result.metadata or {}).get("fallback_reason")
            published_count = len(submission.findings)
            emit_verdict(
                get_tracer_from_settings(settings),
                agent_verdict=submission.verdict,
                structural_verdict="pass" if outcome is RunOutcome.passed else "fail",
                published_count=published_count,
                # Withdrawn ≈ proposed by the agent but not published.
                withdrawn_count=max(len(tool_state.agent_findings) - published_count, 0),
                fallback_reason=str(fallback_reason) if fallback_reason else None,
            )
        except Exception as exc:
            logger.debug("verdict span emission skipped: {}", exc)
