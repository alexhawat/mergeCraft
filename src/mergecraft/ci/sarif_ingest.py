"""Action-side CI SARIF ingest after wait-for-ci completes (D9 / #600)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.ci.intelligence import collect_ci_sarif_findings, warn_ci_evidence
from mergecraft.scm.github import github_client_from_scm

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

CiWaitState = Literal["complete", "timeout", "absent", "skipped", "pending"]


def ci_wait_inputs_from_env() -> tuple[str, int] | None:
    """Read wait-for-ci outputs forwarded by the consumer workflow into the Action env.

    Accepts ``MERGECRAFT_CI_WAIT_STATE`` / ``MERGECRAFT_CI_FAILED_COUNT`` or the
    ``CI_STATE`` / ``CI_FAILED_COUNT`` aliases — both pairs are set in dogfood
    ``mergecraft.yml`` for backward-compatible consumer templates.
    """
    state = (os.environ.get("MERGECRAFT_CI_WAIT_STATE") or os.environ.get("CI_STATE") or "").strip()
    if not state:
        return None
    raw_count = (
        os.environ.get("MERGECRAFT_CI_FAILED_COUNT") or os.environ.get("CI_FAILED_COUNT") or "0"
    ).strip()
    try:
        failed_count = int(raw_count)
    except ValueError:
        warn_ci_evidence(
            f"ci evidence: failed to parse CI_FAILED_COUNT env value {raw_count!r} — using 0"
        )
        failed_count = 0
    return state, failed_count


async def ingest_ci_sarif_for_head_sha(ctx: ToolContext, head_sha: str) -> None:
    """List workflow runs for ``head_sha`` and record declared SARIF artifacts.

    Shared by the action-side wait-for-ci lane and ``run_ci_intelligence``.
    """
    if not head_sha.strip():
        return

    from mergecraft.ci.evidence import record_ci_findings, record_ci_ingest_metadata

    client = github_client_from_scm(ctx.scm)
    if client is None:
        warn_ci_evidence("ci evidence: SARIF ingest skipped — no GitHub client")
        return

    try:
        listed = await client.list_workflow_runs_for_head_sha(
            ctx.repo.owner,
            ctx.repo.name,
            head_sha.strip(),
        )
    except Exception as err:
        warn_ci_evidence(f"ci evidence: workflow run listing failed for {head_sha[:7]} — {err}")
        return

    if listed.incomplete:
        warn_ci_evidence(
            f"ci evidence: workflow run listing truncated for {head_sha[:7]} — "
            "not treating as complete"
        )
        return

    findings = await collect_ci_sarif_findings(ctx, client=client, runs=listed.items)
    if findings:
        record_ci_findings(ctx.tool_state, findings)

    coverage_names = [name.strip() for name in ctx.ci_coverage_artifacts if name.strip()]
    mutation_names = [name.strip() for name in ctx.ci_mutation_artifacts if name.strip()]
    if coverage_names or mutation_names:
        from mergecraft.ci.coverage import coverage_inputs_from_context

        diff, source_tree = coverage_inputs_from_context(ctx)
        try:
            listed_checks = await client.list_check_runs_for_ref(
                ctx.repo.owner, ctx.repo.name, head_sha.strip()
            )
            if listed_checks.incomplete:
                warn_ci_evidence(
                    f"ci evidence: coverage check-run listing truncated for {head_sha[:7]} — "
                    "not treating as complete"
                )
                check_runs = None
            else:
                check_runs = list(listed_checks.items)
        except Exception as check_err:
            warn_ci_evidence(
                f"ci evidence: coverage check-run listing failed for {head_sha[:7]} — {check_err}"
            )
            check_runs = None
        if coverage_names:
            from mergecraft.ci.coverage import collect_ci_coverage_findings

            coverage = await collect_ci_coverage_findings(
                ctx,
                client=client,
                runs=listed.items,
                artifacts=coverage_names,
                diff=diff,
                source_tree=source_tree,
                check_runs=check_runs,
            )
            record_ci_ingest_metadata(
                ctx.tool_state,
                run_notes=coverage.run_notes,
                skip_reason=coverage.skip_reason,
            )
            if coverage.findings:
                record_ci_findings(ctx.tool_state, coverage.findings)
        if mutation_names:
            from mergecraft.ci.changed_functions import changed_functions_from_diff
            from mergecraft.ci.mutation import collect_ci_mutation_findings

            symbols = changed_functions_from_diff(diff, source_tree)
            mutation = await collect_ci_mutation_findings(
                ctx,
                client=client,
                runs=listed.items,
                artifacts=mutation_names,
                changed_functions=symbols,
                diff=diff,
                source_tree=source_tree,
                check_runs=check_runs,
            )
            record_ci_ingest_metadata(ctx.tool_state, skip_reason=mutation.skip_reason)
            if mutation.findings:
                record_ci_findings(ctx.tool_state, mutation.findings)


async def ingest_ci_sarif_after_ci_wait(
    ctx: ToolContext,
    *,
    ci_wait_state: CiWaitState | str,
    head_sha: str,
    ci_failed_count: int = 0,
) -> None:
    """Ingest declared CI SARIF artifacts after wait-for-ci reaches ``complete``.

    ``complete`` covers green and red CI — ingest runs whenever the wait job
    finished polling, not only when Verify jobs failed. All other wait states
    skip ingest with a debug log. ``workflow_dispatch`` does not pre-ingest
    SARIF because the wait job is PR-only.
    """
    if ci_wait_state != "complete":
        logger.debug(
            "ci evidence: SARIF ingest skipped — wait state {} does not fetch artifacts",
            ci_wait_state,
        )
        return
    if ci_failed_count:
        logger.info(
            "ci evidence: ingesting declared SARIF after complete wait with {} failed job(s)",
            ci_failed_count,
        )
    await ingest_ci_sarif_for_head_sha(ctx, head_sha)


async def ingest_ci_sarif_from_action_env(
    tool_context: ToolContext,
    gh_event: dict[str, Any],
    *,
    event_name: str | None = None,
) -> None:
    """Action-side SARIF ingest lane — not agent-invoked (D9)."""
    wait_inputs = ci_wait_inputs_from_env()
    if wait_inputs is None:
        return
    ci_wait_state, ci_failed_count = wait_inputs
    from mergecraft.config.trust_policy import bound_head_sha

    resolved_event = event_name or os.environ.get("GITHUB_EVENT_NAME", "")
    head_sha = bound_head_sha(gh_event, event_name=resolved_event)
    if not head_sha:
        return
    await ingest_ci_sarif_after_ci_wait(
        tool_context,
        ci_wait_state=ci_wait_state,
        ci_failed_count=ci_failed_count,
        head_sha=head_sha,
    )


__all__ = [
    "CiWaitState",
    "ci_wait_inputs_from_env",
    "ingest_ci_sarif_after_ci_wait",
    "ingest_ci_sarif_for_head_sha",
    "ingest_ci_sarif_from_action_env",
]
