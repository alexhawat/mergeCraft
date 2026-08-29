"""Opt-in commit-status check-runs (``mergecraft`` / ``mergecraft-approval``).

The approval check-run posts ``packet.decision.verdict`` (W8). When
``packet`` is None, post ``neutral`` without assembling a packet.
Narrative
(``ApprovalRecord.would_approve``, ``result.output``, anything the model
wrote) is recorded separately as an advisory input and is never the sole
positive input — see ``decide_approval`` in ``mergecraft.agents.gates`` for
the full contract (D12, D13, D14).

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
from mergecraft.utils import gha_log

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding
    from mergecraft.analyzers.manifest import TrustTier
    from mergecraft.evidence.packet import MergeEvidencePacket
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.tool_state import ApprovalRecord

COMPLETION_CHECK = "mergecraft"
APPROVAL_CHECK = "mergecraft-approval"
Conclusion = Literal["success", "failure", "neutral"]


def _run_url(ctx: ToolContext) -> str | None:
    if not ctx.run_id:
        return None
    return f"https://github.com/{ctx.repo.owner}/{ctx.repo.name}/actions/runs/{ctx.run_id}"


def _reviewed_sha(
    approval: ApprovalRecord | None,
    packet: MergeEvidencePacket | None,
) -> str | None:
    if approval and approval.sha:
        return approval.sha
    if packet is not None and packet.self_assessment is not None and packet.self_assessment.sha:
        return packet.self_assessment.sha
    return None


def _http_status_from_error(err: BaseException) -> int | None:
    response = getattr(err, "response", None)
    status = getattr(response, "status_code", None)
    return int(status) if isinstance(status, int) else None


def _log_check_post_failure(
    *,
    check_name: str,
    head_sha: str,
    err: BaseException,
) -> None:
    status = _http_status_from_error(err)
    status_text = f" HTTP {status}" if status is not None else ""
    message = f"status checks: {check_name} post failed on {head_sha[:7]}{status_text}: {err}"
    logger.warning(message)
    gha_log.warning(message)


def _change_findings(findings: list[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.scope != "run"]


def _run_health_findings(findings: list[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.scope == "run"]


def _finding_label(finding: Finding) -> str:
    return f"{finding.severity} · {finding.tool}/{finding.rule_id}"


def _append_run_metadata(
    lines: list[str],
    *,
    run_url: str | None,
    reviewed_sha: str | None,
) -> None:
    if run_url:
        lines.append(f"Run: {run_url}")
    if reviewed_sha:
        lines.append(f"Reviewed commit: {reviewed_sha}")


def _run_health_lines(findings: list[Finding]) -> list[str]:
    run_health = _run_health_findings(findings)
    if not run_health:
        return []
    lines = ["Run-health findings:"]
    lines.extend(f"- {_finding_label(finding)}: {finding.message}" for finding in run_health)
    return lines


def _build_completion_summary(
    *,
    run_succeeded: bool,
    failure_reason: str | None,
    findings: list[Finding],
    catalog_banner: str | None,
    run_url: str | None,
    reviewed_sha: str | None,
) -> str:
    if run_succeeded:
        lead = "The mergeCraft run finished successfully."
    else:
        lead = (
            failure_reason
            or "The mergeCraft run failed or timed out. See the run logs for details."
        )
    lines = [lead, *_run_health_lines(findings)]
    if catalog_banner:
        lines.append(catalog_banner)
    _append_run_metadata(lines, run_url=run_url, reviewed_sha=reviewed_sha)
    return "\n".join(lines)


def _build_approval_lead(
    approval_conclusion: Conclusion,
    findings: list[Finding],
    *,
    decision_reason: str | None,
) -> str:
    from mergecraft.agents.gates import blocking_findings

    if approval_conclusion == "success":
        return "mergeCraft approved this PR."
    if approval_conclusion == "failure":
        blockers = blocking_findings(findings)
        if blockers:
            names = ", ".join(_finding_label(finding) for finding in blockers)
            count = len(blockers)
            noun = "finding" if count == 1 else "findings"
            return f"mergeCraft found {count} blocking change {noun}: {names}."
        return "mergeCraft would not approve this PR."
    reason = decision_reason or "review did not complete"
    lead = f"The mergeCraft review did not complete: {reason}."
    run_health = _run_health_lines(findings)
    if run_health and not _change_findings(findings):
        return "\n".join([lead, *run_health])
    return lead


def _build_approval_summary(
    *,
    approval_conclusion: Conclusion,
    findings: list[Finding],
    decision_reason: str | None,
    decision_inputs: dict[str, object],
    catalog_banner: str | None,
    run_url: str | None,
    reviewed_sha: str | None,
) -> str:
    from mergecraft.agents.gates import decision_summary_lines

    lines = [_build_approval_lead(approval_conclusion, findings, decision_reason=decision_reason)]
    _append_run_metadata(lines, run_url=run_url, reviewed_sha=reviewed_sha)
    lines.append("Decision inputs:")
    lines.extend(decision_summary_lines(decision_inputs))
    if catalog_banner:
        lines.append(catalog_banner)
    return "\n".join(lines)


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
    status_enabled = payload.status_checks or bool(
        payload.extra.get("statusChecks") or payload.extra.get("status_checks")
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
        logger.warning(
            "status checks: failed to resolve PR #{} head sha: {}",
            pull_number,
            err,
        )
        gha_log.warning(f"status checks: failed to resolve PR #{pull_number} head sha: {err}")
        return

    from mergecraft.mcp.tool_state import primary_repo_state

    completion_sha = primary_repo_state(ctx.tool_state).checkout_sha or head_sha
    completion_conclusion: CompletionConclusion = conclusion or (
        "success" if run_succeeded else "failure"
    )
    catalog_banner = _catalog_unavailable_banner(ctx)
    packet_findings = list(packet.findings) if packet is not None else []
    approval = ctx.tool_state.approval
    run_url = _run_url(ctx)
    reviewed_sha = _reviewed_sha(approval, packet)
    completion_summary = _build_completion_summary(
        run_succeeded=run_succeeded,
        failure_reason=failure_reason,
        findings=packet_findings,
        catalog_banner=catalog_banner,
        run_url=run_url,
        reviewed_sha=reviewed_sha,
    )
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
        _log_check_post_failure(
            check_name=COMPLETION_CHECK,
            head_sha=completion_sha,
            err=err,
        )

    # --- Approval gate (W8.2): post ``packet.decision.verdict``. -------------
    # The agent's boolean is still in ApprovalRecord.would_approve (W8.3) as an
    # advisory input the merge-evidence plan reads. A missing packet posts
    # ``neutral`` so the check still lands; do not rebuild the packet.
    from mergecraft.agents.gates import (
        approval_decision_inputs,
        log_decision,
    )

    # D7 / #460: the packet already ran ``decide_approval``. Reuse
    # ``packet.decision.verdict`` so this layer only posts check-runs.
    # Best-effort: never raise after the completion check-run has posted.
    if packet is None:
        logger.debug("status checks: no packet; posting neutral approval")
        neutral_lines = [
            "The mergeCraft evidence packet was not assembled, so no approval decision was recorded.",
        ]
        _append_run_metadata(neutral_lines, run_url=run_url, reviewed_sha=reviewed_sha)
        try:
            await _create_check_run(
                ctx,
                name=APPROVAL_CHECK,
                head_sha=head_sha,
                conclusion="neutral",
                title="mergeCraft review did not complete",
                summary="\n".join(neutral_lines),
            )
        except Exception as err:
            _log_check_post_failure(
                check_name=APPROVAL_CHECK,
                head_sha=head_sha,
                err=err,
            )
        return

    try:
        tier: TrustTier = ctx.trust_tier
        decision_reason: str | None = None
        if packet.decision is None:
            logger.debug("status checks: packet has no decision; posting neutral approval")
            approval_conclusion: Conclusion = "neutral"
        else:
            approval_conclusion = packet.decision.verdict
            decision_reason = packet.decision.reason
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

        if approval_conclusion == "success":
            approval_title = "mergeCraft would approve"
        elif approval_conclusion == "failure":
            approval_title = "mergeCraft would not approve"
        else:
            approval_title = "mergeCraft review did not complete"

        approval_summary = _build_approval_summary(
            approval_conclusion=approval_conclusion,
            findings=findings,
            decision_reason=decision_reason,
            decision_inputs=decision_inputs,
            catalog_banner=catalog_banner,
            run_url=run_url,
            reviewed_sha=reviewed_sha,
        )

        await _create_check_run(
            ctx,
            name=APPROVAL_CHECK,
            head_sha=head_sha,
            conclusion=approval_conclusion,
            title=approval_title,
            summary=approval_summary,
        )
    except Exception as err:
        _log_check_post_failure(
            check_name=APPROVAL_CHECK,
            head_sha=head_sha,
            err=err,
        )


__all__ = [
    "APPROVAL_CHECK",
    "COMPLETION_CHECK",
    "CompletionConclusion",
    "Conclusion",
    "report_status_checks",
]
