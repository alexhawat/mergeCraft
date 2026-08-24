"""Opt-in commit-status check-runs (``mergecraft`` / ``mergecraft-approval``).

The approval check-run is computed structurally (W8): the conclusion is a pure
function of the typed ``Finding`` list, the run's completion state, and the
trust tier. Narrative (``ApprovalRecord.would_approve``, ``result.output``,
anything the model wrote) is recorded separately as an advisory input and is
never the sole positive input — see ``decide_approval`` in
``mergecraft.agents.gates`` for the full contract (D12, D13, D14).

Wire-shape semantics:

- ``success`` — run completed, trust tier is trusted, no blockers in the finding
  list, and at least one finding attests the review ran.
- ``failure`` — at least one ``Critical`` or ``Major`` finding; the agent's
  narrative cannot outvote a blocker.
- ``neutral`` — run crashed / timed out / produced no findings / untrusted tier;
  the hardened enforce step treats this as blocking (#75, D13).

D3/W5.2 — the ``mergecraft`` completion check's conclusion is driven by the
caller's optional ``conclusion`` (the ``RunOutcome`` -> ``CompletionConclusion``
mapping in ``mergecraft.run_outcome.RUN_OUTCOME_CONCLUSION``) rather than the
bare ``run_succeeded`` boolean, so a timeout can report GitHub's literal
``timed_out`` conclusion instead of being flattened to ``failure``. Callers
that only have the boolean (pre-W5 call sites, tests) keep working unchanged —
``conclusion`` defaults to the old ``success``/``failure`` split.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.run_outcome import CompletionConclusion

if TYPE_CHECKING:
    from mergecraft.analyzers.manifest import TrustTier
    from mergecraft.evidence.packet import MergeEvidencePacket
    from mergecraft.mcp.context import ToolContext

COMPLETION_CHECK = "mergecraft"
APPROVAL_CHECK = "mergecraft-approval"
Conclusion = Literal["success", "failure", "neutral"]


async def _create_check_run(
    ctx: ToolContext,
    *,
    name: str,
    head_sha: str,
    conclusion: CompletionConclusion,
    title: str,
    summary: str,
) -> None:
    body: dict[str, Any] = {
        "name": name,
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": conclusion,
        "output": {"title": title, "summary": summary},
    }
    if ctx.run_id:
        body["details_url"] = (
            f"https://github.com/{ctx.repo.owner}/{ctx.repo.name}/actions/runs/{ctx.run_id}"
        )
    await ctx.scm.post(f"/repos/{ctx.repo.owner}/{ctx.repo.name}/check-runs", json=body)
    logger.info(
        "» posted {} check ({}) on {}",
        name,
        conclusion,
        head_sha[:7],
    )


def _catalog_unavailable_banner(ctx: ToolContext) -> str | None:
    """Return a one-line catalog banner when the analyzer catalog did not run.

    D6 / #459: glanceable ``analyzers: unavailable`` on check-run summaries.
    Omitted when the catalog executed (including mixed passed + skipped).
    """
    run_state = ctx.tool_state.analyzer_run
    if run_state is None:
        return None
    from mergecraft.analyzers.pipeline import CatalogScanStatus, catalog_scan_status

    if catalog_scan_status(run_state) != CatalogScanStatus.UNAVAILABLE:
        return None
    return "analyzers: unavailable"


async def report_status_checks(
    ctx: ToolContext,
    *,
    run_succeeded: bool,
    failure_reason: str | None = None,
    conclusion: CompletionConclusion | None = None,
    packet: MergeEvidencePacket | None = None,
) -> None:
    """Post opt-in status checks. Best-effort; never raises into the run outcome.

    ``conclusion`` (D3/W5.2) overrides the ``mergecraft`` completion check's
    GitHub conclusion — pass ``mergecraft.run_outcome.RUN_OUTCOME_CONCLUSION
    [outcome]`` once a caller has a ``RunOutcome`` rather than a bare bool.
    Omitted, it falls back to the pre-W5 ``success``/``failure`` split driven
    by ``run_succeeded`` alone. The ``mergecraft-approval`` check uses
    ``packet.decision.verdict`` and is skipped when ``packet`` is None.
    """
    payload = ctx.payload
    status_enabled = getattr(payload, "status_checks", False) or (
        isinstance(getattr(payload, "extra", None), dict)
        and bool(payload.extra.get("statusChecks") or payload.extra.get("status_checks"))
    )
    if not status_enabled:
        return

    event = payload.event
    pull_number = event.issue_number
    if event.is_pr is not True or not isinstance(pull_number, int):
        return

    try:
        pr = await ctx.scm.get_pull(ctx.repo.owner, ctx.repo.name, pull_number)
        head_sha = str(pr.get("head", {}).get("sha") or "")
        if not head_sha:
            return
    except Exception as err:
        logger.debug("status checks: failed to resolve PR #{} head sha: {}", pull_number, err)
        return

    from mergecraft.mcp.tool_state import primary_repo_state

    completion_sha = primary_repo_state(ctx.tool_state).checkout_sha or head_sha
    completion_conclusion: CompletionConclusion = conclusion or (
        "success" if run_succeeded else "failure"
    )
    catalog_banner = _catalog_unavailable_banner(ctx)
    completion_summary = (
        "The mergeCraft run finished successfully."
        if run_succeeded
        else (
            failure_reason
            or "The mergeCraft run failed or timed out. See the run logs for details."
        )
    )
    if catalog_banner:
        completion_summary = f"{completion_summary}\n{catalog_banner}"
    try:
        await _create_check_run(
            ctx,
            name=COMPLETION_CHECK,
            head_sha=completion_sha,
            conclusion=completion_conclusion,
            title="mergeCraft run completed" if run_succeeded else "mergeCraft run failed",
            summary=completion_summary,
        )
    except Exception as err:
        logger.debug("status checks: {} post failed: {}", COMPLETION_CHECK, err)

    # --- Approval gate (W8.2): structural conclusion, not narrative. ---------
    # The agent's boolean is still in ApprovalRecord.would_approve (W8.3) as an
    # advisory input the merge-evidence plan reads; the conclusion is computed
    # from typed findings + run state + tier only.
    from mergecraft.agents.gates import (
        approval_decision_inputs,
        decision_summary_lines,
        log_decision,
    )

    # D7 / #460: the packet already ran ``decide_approval``. Reuse
    # ``packet.decision.verdict`` so this layer only posts check-runs.
    # Best-effort: never raise after the completion check-run has posted.
    if packet is None:
        logger.debug("status checks: no packet; skipping approval check")
        return

    try:
        tier: TrustTier = ctx.trust_tier
        if packet.decision is None:
            logger.debug("status checks: packet has no decision; posting neutral approval")
            approval_conclusion: Conclusion = "neutral"
        else:
            approval_conclusion = packet.decision.verdict
        findings = list(packet.findings)
        decision_inputs = approval_decision_inputs(
            findings,
            run_succeeded=run_succeeded,
            tier=tier,
        )
        log_decision(
            findings,
            run_succeeded=run_succeeded,
            tier=tier,
            conclusion=approval_conclusion,
        )

        approval = ctx.tool_state.approval
        if approval_conclusion == "success":
            approval_title = "mergeCraft would approve"
            approval_summary = "mergeCraft has no outstanding review feedback on this PR."
        elif approval_conclusion == "failure":
            approval_title = "mergeCraft would not approve"
            approval_summary = (
                "mergeCraft has outstanding review feedback or requested changes on this PR."
            )
        else:
            approval_title = "mergeCraft review did not complete"
            approval_summary = (
                "The mergeCraft review did not complete, so no approval decision was recorded."
            )

        if approval and approval.sha:
            approval_summary = f"{approval_summary} Reviewed commit: {approval.sha}."
        approval_summary = f"{approval_summary}\nDecision inputs:\n" + "\n".join(
            decision_summary_lines(decision_inputs)
        )
        if catalog_banner:
            approval_summary = f"{approval_summary}\n{catalog_banner}"

        await _create_check_run(
            ctx,
            name=APPROVAL_CHECK,
            head_sha=head_sha,
            conclusion=approval_conclusion,
            title=approval_title,
            summary=approval_summary,
        )
    except Exception as err:
        logger.debug("status checks: {} post failed: {}", APPROVAL_CHECK, err)


__all__ = [
    "APPROVAL_CHECK",
    "COMPLETION_CHECK",
    "CompletionConclusion",
    "Conclusion",
    "report_status_checks",
]
