"""Action-side CI SARIF ingest after wait-for-ci completes (D9 / #600)."""

from __future__ import annotations

import os
import zipfile
from io import BytesIO
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.ci.intelligence import collect_ci_sarif_findings, warn_ci_evidence
from mergecraft.ci.red_green import (
    RECEIPT_MAX_BYTES,
    RedGreenEvidence,
    RedGreenReceiptError,
    parse_red_green_receipt,
    receipt_matches,
    red_green_verdict,
    undeclared_red_green_evidence,
)
from mergecraft.scm.github import github_client_from_scm

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from mergecraft.ci.red_green import RedGreenStatus
    from mergecraft.mcp.context import ToolContext
    from mergecraft.utils.github import GitHubClient

CiWaitState = Literal["complete", "timeout", "absent", "skipped", "pending"]


def ci_wait_inputs_from_env() -> tuple[str, int] | None:
    """Read wait-for-ci outputs forwarded by the consumer workflow into the Action env.

    Accepts ``MERGECRAFT_CI_WAIT_STATE`` / ``MERGECRAFT_CI_FAILED_COUNT`` or the
    ``CI_STATE`` / ``CI_FAILED_COUNT`` aliases — both pairs are set in dogfood
    ``mergecraft.yml`` for backward-compatible consumer templates.
    """
    from mergecraft.config.env import RunInputsEnv

    env = RunInputsEnv()
    state = (env.ci_wait_state or "").strip()
    if not state:
        return None
    raw_count = (env.ci_failed_count or "0").strip()
    try:
        failed_count = int(raw_count)
    except ValueError:
        warn_ci_evidence(
            f"ci evidence: failed to parse CI_FAILED_COUNT env value {raw_count!r} — using 0"
        )
        failed_count = 0
    return state, failed_count


_RECEIPT_MEMBER = "red-green.json"


def _successful_run_on(run: Mapping[str, Any], head_sha: str) -> bool:
    """A finished, successful workflow run on exactly ``head_sha`` (listing row fields)."""
    return (
        run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and str(run.get("head_sha") or "").strip().lower() == head_sha
    )


def _receipt_member_bytes(archive: bytes) -> bytes | None:
    """The receipt member of an artifact zip, read at most one byte past the cap.

    Prefers a member named ``red-green.json``, else the first ``.json`` member.
    Nothing in the archive is executed or written to disk; ``None`` when the
    archive holds no JSON member.
    """
    with zipfile.ZipFile(BytesIO(archive)) as zf:
        members = [
            info
            for info in zf.infolist()
            if not info.is_dir() and info.filename.lower().endswith(".json")
        ]
        if not members:
            return None
        named = [m for m in members if m.filename.rsplit("/", 1)[-1].lower() == _RECEIPT_MEMBER]
        chosen = (named or members)[0]
        with zf.open(chosen) as member:
            return member.read(RECEIPT_MAX_BYTES + 1)


def _evidence_from_archive(
    archive: bytes,
    *,
    artifact: str,
    run_url: str | None,
    base_sha: str,
    head_sha: str,
) -> RedGreenEvidence:
    """Parse, bind and judge the receipt in one downloaded artifact; never raises."""

    def _row(status: RedGreenStatus, detail: str, test_count: int = 0) -> RedGreenEvidence:
        return RedGreenEvidence(
            status=status,
            test_count=test_count,
            artifact=artifact,
            run_url=run_url,
            detail=detail,
        )

    try:
        raw = _receipt_member_bytes(archive)
    except Exception as err:
        return _row("invalid", f"artifact {artifact} is not a readable zip ({type(err).__name__})")
    if raw is None:
        return _row("no-receipt", f"artifact {artifact} holds no JSON receipt")
    try:
        receipt = parse_red_green_receipt(raw)
    except RedGreenReceiptError as err:
        prefix = "receipt oversized" if err.kind == "oversized" else "receipt invalid"
        return _row("invalid", f"{prefix}: {err}")
    count = len(receipt.tests)
    if not receipt_matches(receipt, base_sha=base_sha, head_sha=head_sha):
        return _row(
            "mismatch",
            "the receipt's base and head SHAs do not match this pull request's",
            count,
        )
    verdict = red_green_verdict(receipt)
    return _row(verdict, f"receipt lists {count} test(s): {verdict}", count)


async def collect_ci_red_green_evidence(
    ctx: ToolContext,
    *,
    client: GitHubClient,
    runs: Sequence[Mapping[str, Any]],
    artifacts: Sequence[str],
    base_sha: str,
    head_sha: str,
) -> RedGreenEvidence:
    """Read the declared fail-then-pass receipt from a successful run on ``head_sha``.

    Undeclared (no non-blank name) is ``not-declared`` with no API call. Only a
    listing row with ``status == "completed"``, ``conclusion == "success"`` and
    ``head_sha`` equal to the head is read; the first such run carrying a named
    artifact decides. The receipt is parsed as data (never executed), bound to
    ``base_sha`` / ``head_sha`` and judged. A failed listing or download, a
    missing artifact or no successful run is ``no-receipt``. Never raises.

    Args:
        ctx (ToolContext): The run context (repository identity).
        client (GitHubClient): The GitHub client for listings and downloads.
        runs (Sequence[Mapping[str, Any]]): Workflow runs listed for the head SHA.
        artifacts (Sequence[str]): ``ciEvidence.redGreenArtifacts``.
        base_sha (str): The run's bound base SHA.
        head_sha (str): The run's bound head SHA.

    Returns:
        RedGreenEvidence: What the run recorded about its receipt.
    """
    wanted = {name.strip() for name in artifacts if name.strip()}
    if not wanted:
        return undeclared_red_green_evidence()
    head = head_sha.strip().lower()
    detail = f"no successful workflow run on {head[:7] or 'the head'} uploaded a receipt"
    for run in runs:
        run_id = run.get("id")
        if not isinstance(run_id, int) or not _successful_run_on(run, head):
            continue
        raw_url = run.get("html_url")
        run_url = raw_url if isinstance(raw_url, str) and raw_url else None
        try:
            listed = await client.list_workflow_run_artifacts(ctx.repo.owner, ctx.repo.name, run_id)
        except Exception as err:
            logger.warning("ci evidence: receipt listing failed for run {} — {}", run_id, err)
            detail = f"artifact listing failed for run {run_id}"
            continue
        if listed.incomplete:
            detail = f"artifact listing truncated for run {run_id}"
            continue
        for item in listed.items:
            name = str(item.get("name") or "")
            artifact_id = item.get("id")
            if name not in wanted or not isinstance(artifact_id, int):
                continue
            try:
                archive = await client.download_artifact_zip(
                    ctx.repo.owner, ctx.repo.name, artifact_id
                )
            except Exception as err:
                logger.warning("ci evidence: receipt artifact {} download failed — {}", name, err)
                detail = f"artifact {name} download failed for run {run_id}"
                continue
            return _evidence_from_archive(
                bytes(archive),
                artifact=name,
                run_url=run_url,
                base_sha=base_sha,
                head_sha=head_sha,
            )
    return RedGreenEvidence(
        status="no-receipt", test_count=0, artifact=None, run_url=None, detail=detail
    )


def _bound_base_sha(ctx: ToolContext) -> str:
    """The base SHA of the run's bound pull request, or ``""`` when it has none."""
    event = ctx.gh_event if isinstance(ctx.gh_event, dict) else {}
    pull = event.get("pull_request")
    base = pull.get("base") if isinstance(pull, dict) else None
    sha = base.get("sha") if isinstance(base, dict) else None
    return sha.strip() if isinstance(sha, str) else ""


async def ingest_ci_sarif_for_head_sha(ctx: ToolContext, head_sha: str) -> None:
    """List workflow runs for ``head_sha`` and record declared SARIF artifacts.

    Shared by the action-side wait-for-ci lane and ``run_ci_intelligence``.
    """
    if not head_sha.strip():
        return

    from mergecraft.ci.evidence import (
        record_ci_findings,
        record_ci_ingest_metadata,
        record_sarif_findings,
    )

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
        record_sarif_findings(ctx.tool_state, findings)

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

    red_green_names = [name.strip() for name in ctx.ci_red_green_artifacts if name.strip()]
    if red_green_names:
        try:
            ctx.tool_state.red_green = await collect_ci_red_green_evidence(
                ctx,
                client=client,
                runs=listed.items,
                artifacts=red_green_names,
                base_sha=_bound_base_sha(ctx),
                head_sha=head_sha.strip(),
            )
        except Exception as err:  # the collector is total; this is belt and braces
            warn_ci_evidence(f"ci evidence: receipt ingest failed for {head_sha[:7]} — {err}")


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
    "collect_ci_red_green_evidence",
    "ingest_ci_sarif_after_ci_wait",
    "ingest_ci_sarif_for_head_sha",
    "ingest_ci_sarif_from_action_env",
]
