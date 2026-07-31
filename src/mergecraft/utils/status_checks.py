"""Opt-in commit-status check-runs (``mergecraft`` / ``mergecraft-approval``)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

COMPLETION_CHECK = "mergecraft"
APPROVAL_CHECK = "mergecraft-approval"
Conclusion = Literal["success", "failure", "neutral"]


async def _create_check_run(
    ctx: ToolContext,
    *,
    name: str,
    head_sha: str,
    conclusion: Conclusion,
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
    await ctx.github.post(f"/repos/{ctx.repo.owner}/{ctx.repo.name}/check-runs", json=body)
    logger.info(
        "» posted {} check ({}) on {}",
        name,
        conclusion,
        head_sha[:7],
    )


async def report_status_checks(
    ctx: ToolContext,
    *,
    run_succeeded: bool,
    failure_reason: str | None = None,
) -> None:
    """Post opt-in status checks. Best-effort; never raises into the run outcome."""
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
        pr = await ctx.github.get_pull(ctx.repo.owner, ctx.repo.name, pull_number)
        head_sha = str(pr.get("head", {}).get("sha") or "")
        if not head_sha:
            return
    except Exception as err:
        logger.debug("status checks: failed to resolve PR #{} head sha: {}", pull_number, err)
        return

    from mergecraft.mcp.tool_state import primary_repo_state

    completion_sha = primary_repo_state(ctx.tool_state).checkout_sha or head_sha
    try:
        await _create_check_run(
            ctx,
            name=COMPLETION_CHECK,
            head_sha=completion_sha,
            conclusion="success" if run_succeeded else "failure",
            title="mergeCraft run completed" if run_succeeded else "mergeCraft run failed",
            summary=(
                "The mergeCraft run finished successfully."
                if run_succeeded
                else (
                    failure_reason
                    or "The mergeCraft run failed or timed out. See the run logs for details."
                )
            ),
        )
    except Exception as err:
        logger.debug("status checks: {} post failed: {}", COMPLETION_CHECK, err)

    approval = ctx.tool_state.approval
    if run_succeeded and approval and approval.would_approve:
        approval_conclusion: Conclusion = "success"
        approval_title = "mergeCraft would approve"
        approval_summary = "mergeCraft has no outstanding review feedback on this PR."
    elif run_succeeded and approval and not approval.would_approve:
        approval_conclusion = "failure"
        approval_title = "mergeCraft would not approve"
        approval_summary = (
            "mergeCraft has outstanding review feedback or requested changes on this PR."
        )
    else:
        approval_conclusion = "neutral"
        approval_title = "mergeCraft review did not complete"
        approval_summary = (
            "The mergeCraft review did not complete, so no approval decision was recorded."
        )

    if approval and approval.sha:
        approval_summary = f"{approval_summary} Reviewed commit: {approval.sha}."

    try:
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


__all__ = ["APPROVAL_CHECK", "COMPLETION_CHECK", "report_status_checks"]
