"""Action-side CI SARIF ingest after wait-for-ci completes (D9 / #600)."""

from __future__ import annotations

import os
import zipfile
from collections.abc import Mapping
from io import BytesIO
from typing import TYPE_CHECKING, Any, Final, Literal

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
from mergecraft.scm.artifact_provenance import (
    declared_artifact_archive,
    provenanced_runs,
    require_workflow_untouched,
    workflow_path,
)
from mergecraft.scm.github import github_client_from_scm

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mergecraft.ci.red_green import RedGreenStatus
    from mergecraft.config.settings import RedGreenReceiptSettings
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
RED_GREEN_ARCHIVE_MAX_BYTES: Final[int] = 2 * 1024 * 1024
"""The largest receipt archive (``size_in_bytes``) that is ever downloaded."""


class _NoReceipt(Exception):
    """No receipt can count for this run; the message is the evidence detail."""


def _short(sha: str) -> str:
    return sha[:7] if sha else "unknown"


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
        # An oversized error already says so; an invalid one gets its own prefix.
        detail = str(err) if err.kind == "oversized" else f"receipt invalid: {err}"
        return _row("invalid", detail)
    count = len(receipt.tests)
    if not receipt_matches(receipt, base_sha=base_sha, head_sha=head_sha):
        return _row(
            "mismatch",
            f"the receipt names base {_short(receipt.base_sha)} and head "
            f"{_short(receipt.head_sha)}, this pull request is at base {_short(base_sha)} "
            f"and head {_short(head_sha)}",
            count,
        )
    verdict = red_green_verdict(receipt)
    return _row(verdict, f"receipt lists {count} test(s): {verdict}", count)


def _no_receipt(detail: str, *, artifact: str | None = None) -> RedGreenEvidence:
    return RedGreenEvidence(
        status="no-receipt", test_count=0, artifact=artifact, run_url=None, detail=detail
    )


async def collect_ci_red_green_evidence(
    ctx: ToolContext,
    *,
    client: GitHubClient,
    runs: Sequence[Mapping[str, Any]],
    declaration: RedGreenReceiptSettings | None,
    base_sha: str,
    head_sha: str,
) -> RedGreenEvidence:
    """Read the declared fail-then-pass receipt for this head; never raises.

    No declaration is ``not-declared`` with no API call. The pull request must leave
    the declared workflow untouched (judged on the unfiltered change set; any doubt
    fails closed), and only a run of exactly that workflow, from the reviewed
    repository, completed with ``success`` on the head SHA may supply the artifact.
    Its listed ``size_in_bytes`` must be known and at most 2 MiB before it is
    downloaded. The receipt is parsed as data (never executed), bound to
    ``base_sha`` / ``head_sha`` and judged. Every other outcome is ``no-receipt``
    with the reason in ``detail``.

    Args:
        ctx (ToolContext): The run context (repository identity, review diff).
        client (GitHubClient): The GitHub client for listings and downloads.
        runs (Sequence[Mapping[str, Any]]): Workflow runs listed for the head SHA.
        declaration (RedGreenReceiptSettings | None): The base-side ``ciEvidence.redGreen``.
        base_sha (str): The run's bound base SHA.
        head_sha (str): The run's bound head SHA.

    Returns:
        RedGreenEvidence: What the run recorded about its receipt.
    """
    if declaration is None:
        return undeclared_red_green_evidence()
    artifact = declaration.artifact
    workflow = workflow_path(declaration.workflow)
    label = f"the receipt artifact '{artifact}'"
    head = head_sha.strip().lower()
    owner, repo = ctx.repo.owner, ctx.repo.name
    try:
        require_workflow_untouched(
            ctx.tool_state, workflow=workflow, label=label, refuse=_NoReceipt
        )
        provenanced = provenanced_runs(
            [run for run in runs if isinstance(run, Mapping)],
            head=head,
            workflow=workflow,
            repo=f"{owner}/{repo}",
            label=label,
            refuse=_NoReceipt,
            short=_short,
        )
        run, archive = await declared_artifact_archive(
            client,
            owner=owner,
            repo=repo,
            runs=provenanced,
            artifact=artifact,
            label=label,
            max_bytes=RED_GREEN_ARCHIVE_MAX_BYTES,
            refuse=_NoReceipt,
        )
    except _NoReceipt as absent:
        logger.info("ci evidence: no fail-then-pass receipt — {}", absent)
        return _no_receipt(str(absent))
    except Exception as err:  # the steps above are total; this keeps the run going regardless
        logger.warning("ci evidence: receipt ingest failed — {}", err)
        return _no_receipt(f"{label} could not be read ({type(err).__name__})")
    raw_url = run.get("html_url")
    run_url = raw_url if isinstance(raw_url, str) and raw_url else None
    return _evidence_from_archive(
        archive, artifact=artifact, run_url=run_url, base_sha=base_sha, head_sha=head_sha
    )


def _bound_base_sha(ctx: ToolContext) -> str:
    """The base SHA of the run's bound pull request, or ``""`` when it has none."""
    event = ctx.gh_event if isinstance(ctx.gh_event, dict) else {}
    pull = event.get("pull_request")
    base = pull.get("base") if isinstance(pull, dict) else None
    sha = base.get("sha") if isinstance(base, dict) else None
    return sha.strip() if isinstance(sha, str) else ""


async def ingest_ci_sarif_for_head_sha(
    ctx: ToolContext, head_sha: str, *, red_green: bool = True
) -> None:
    """List workflow runs for ``head_sha`` and record declared SARIF artifacts.

    Shared by the action-side wait-for-ci lane and ``run_ci_intelligence``. With
    ``red_green`` (the default) it also reads the fail-then-pass receipt declared on
    ``ToolState.red_green_declaration``; the review run passes ``False`` here, before
    the review diff exists, and reads the receipt after the agent phase
    (:func:`ingest_red_green_after_review`).
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

    declaration = getattr(ctx.tool_state, "red_green_declaration", None)
    if red_green and declaration is not None:
        await _record_red_green(ctx, client=client, runs=listed.items, head_sha=head_sha)


async def _record_red_green(
    ctx: ToolContext, *, client: GitHubClient, runs: Sequence[Any], head_sha: str
) -> None:
    """Collect the declared receipt onto ``ToolState.red_green``; never raises."""
    try:
        ctx.tool_state.red_green = await collect_ci_red_green_evidence(
            ctx,
            client=client,
            runs=runs,
            declaration=getattr(ctx.tool_state, "red_green_declaration", None),
            base_sha=_bound_base_sha(ctx),
            head_sha=head_sha.strip(),
        )
    except Exception as err:  # the collector is total; this is belt and braces
        warn_ci_evidence(f"ci evidence: receipt ingest failed for {head_sha[:7]} — {err}")
        ctx.tool_state.red_green = _no_receipt(f"the receipt ingest failed ({type(err).__name__})")


def record_unverified_red_green(ctx: ToolContext, *, reason: str) -> None:
    """Record ``no-receipt`` for a declared receipt that this run cannot verify.

    Used when the agent never produced a review diff (a skipped or lite run), so the
    declared workflow cannot be shown untouched. Does nothing without a declaration,
    and never overwrites evidence already recorded.

    Args:
        ctx (ToolContext): The run context.
        reason (str): Why the change set is unavailable.
    """
    state = ctx.tool_state
    declaration = getattr(state, "red_green_declaration", None)
    if declaration is None or getattr(state, "red_green", None) is not None:
        return
    state.red_green = _no_receipt(
        f"whether this pull request changes the declared workflow "
        f"{workflow_path(declaration.workflow)} could not be verified: {reason}"
    )


async def ingest_red_green_after_review(
    ctx: ToolContext,
    gh_event: dict[str, Any],
    *,
    event_name: str | None = None,
) -> None:
    """Read the declared fail-then-pass receipt once the review diff exists (#1056).

    The action-side SARIF lane runs before the agent's ``checkout_pr`` writes the
    review diff, so the receipt is read here, after the agent phase and before the
    packet is assembled: the unfiltered change set (diff, ignored and unreviewable
    paths) is on ``ToolState`` by then. Like the SARIF lane it reads CI artifacts
    only after ``wait-for-ci`` reports ``complete``. Never raises.

    Args:
        ctx (ToolContext): The run context.
        gh_event (dict[str, Any]): The bound GitHub event.
        event_name (str | None): ``GITHUB_EVENT_NAME``; read from the env when omitted.
    """
    if getattr(ctx.tool_state, "red_green_declaration", None) is None:
        return
    try:
        wait_inputs = ci_wait_inputs_from_env()
        if wait_inputs is None or wait_inputs[0] != "complete":
            state = "not forwarded" if wait_inputs is None else wait_inputs[0]
            ctx.tool_state.red_green = _no_receipt(
                f"CI had not completed (wait-for-ci state {state}), so no receipt was read"
            )
            return
        from mergecraft.config.trust_policy import bound_head_sha

        resolved_event = event_name or os.environ.get("GITHUB_EVENT_NAME", "")
        head_sha = bound_head_sha(gh_event, event_name=resolved_event)
        client = github_client_from_scm(ctx.scm)
        if not head_sha or client is None:
            ctx.tool_state.red_green = _no_receipt(
                "the head commit or the GitHub client is unknown, so no receipt was read"
            )
            return
        listed = await client.list_workflow_runs_for_head_sha(
            ctx.repo.owner, ctx.repo.name, head_sha.strip()
        )
    except Exception as err:  # a transport failure records no receipt, never a crash
        ctx.tool_state.red_green = _no_receipt(
            f"the workflow runs on the head commit could not be listed ({type(err).__name__})"
        )
        return
    if listed.incomplete:
        ctx.tool_state.red_green = _no_receipt(
            f"the workflow-run listing for {_short(head_sha)} was incomplete, so no receipt "
            "was read"
        )
        return
    await _record_red_green(ctx, client=client, runs=listed.items, head_sha=head_sha)


async def ingest_ci_sarif_after_ci_wait(
    ctx: ToolContext,
    *,
    ci_wait_state: CiWaitState | str,
    head_sha: str,
    ci_failed_count: int = 0,
    red_green: bool = True,
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
    await ingest_ci_sarif_for_head_sha(ctx, head_sha, red_green=red_green)


async def ingest_ci_sarif_from_action_env(
    tool_context: ToolContext,
    gh_event: dict[str, Any],
    *,
    event_name: str | None = None,
    red_green: bool = True,
) -> None:
    """Action-side SARIF ingest lane — not agent-invoked (D9).

    The review run passes ``red_green=False``: this lane runs before the review diff
    exists, so the receipt is read later by :func:`ingest_red_green_after_review`.
    """
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
        red_green=red_green,
    )


__all__ = [
    "RED_GREEN_ARCHIVE_MAX_BYTES",
    "CiWaitState",
    "ci_wait_inputs_from_env",
    "collect_ci_red_green_evidence",
    "ingest_ci_sarif_after_ci_wait",
    "ingest_ci_sarif_for_head_sha",
    "ingest_ci_sarif_from_action_env",
    "ingest_red_green_after_review",
    "record_unverified_red_green",
]
