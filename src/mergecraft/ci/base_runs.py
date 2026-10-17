"""Produce ``base_branch_runs`` for CI attribution without the agent's help (#891).

``analyze_ci_failures`` can clear a failure as pre-existing only when a *failing*
base-branch run carries the same failure fingerprint. Nothing used to read the base
branch on the run's behalf, so that evidence existed only if the agent fetched and
passed it by hand — and a red check could be dismissed in prose with no record.

This producer reads the base branch's recent completed runs of the workflows that
failed on the PR head, fingerprints the failing ones with the exact pipeline the
head failures go through, and keeps only rows whose fingerprint appears in the
current analysis. It is evidence, not a verdict: only a same-fingerprint ``failure``
ever clears a failure (that rule lives in ``ci/flaky.py`` / ``ci/blame.py`` and is
unchanged), a passing or unrecognised base never does, and there is no auto-approval.

Module: mergecraft.ci.base_runs
Depends: mergecraft.ci.{normalize,intelligence,archive_bounds,log_excerpt}, loguru

Exports:
    Classes:
        BaseRunsCollection — The rows used plus an explanatory note when none could be read.
    Functions:
        collect_base_branch_runs — Read the base branch's recent runs for the analysed fingerprints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

#: Completed base runs inspected per failing workflow (newest first).
MAX_BASE_RUNS_PER_WORKFLOW = 3
#: Failing workflows consulted, and base-run log downloads, per analysis.
MAX_WORKFLOWS = 5
MAX_LOG_DOWNLOADS = 6


@dataclass(frozen=True)
class BaseRunsCollection:
    """The base-branch run rows an analysis used, and why none were when empty."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    note: str | None = None


def base_branch_from_event(event: dict[str, Any] | None) -> str | None:
    """Return the PR's base branch name from the bound event, or ``None``."""
    if not isinstance(event, dict):
        return None
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict):
        return None
    base = pull_request.get("base")
    if not isinstance(base, dict):
        return None
    ref = base.get("ref")
    return ref.strip() if isinstance(ref, str) and ref.strip() else None


def _conclusion(run: dict[str, Any]) -> str:
    return str(run.get("conclusion") or "").strip().lower()


def _fingerprint_for_logs(job_name: str, run_id: int, log_text: str) -> str:
    """Fingerprint a base run's log through the same path a head failure takes."""
    from mergecraft.ci.intelligence import provider_jobs_to_raw_failures
    from mergecraft.ci.log_excerpt import analyze_log
    from mergecraft.ci.normalize import normalize_failure

    analysis = analyze_log(log_text)
    job = {
        "job_id": run_id,
        "job_name": job_name,
        "excerpt": {"content": analysis["excerpt"]["content"]},
        "log_index": analysis["index"],
    }
    raw = provider_jobs_to_raw_failures([job])[0]
    return normalize_failure(raw)["failure_fingerprint"]


async def collect_base_branch_runs(
    ctx: ToolContext,
    *,
    client: Any,
    current_runs: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
) -> BaseRunsCollection:
    """Read the base branch's recent runs for the fingerprints in the current analysis.

    Total and non-throwing: any failure degrades to "no base evidence" with a note, so
    the analysis falls back to exactly what it reported before this producer existed.

    Args:
        ctx (ToolContext): The run context (repo identity and the bound event).
        client: The GitHub client; must expose ``list_workflow_runs_for_branch``.
        current_runs (list[dict[str, Any]]): Workflow runs of the PR head's check suite.
        jobs (list[dict[str, Any]]): The provider's per-run job payloads for the failed
            runs (``job_id`` is the workflow run id).

    Returns:
        BaseRunsCollection: Rows shaped like ``ci/flaky.py`` reads them
        (``ref``/``conclusion``/``fingerprint``) plus ``run_id``/``workflow``/``url``.
    """
    from mergecraft.ci.intelligence import provider_jobs_to_raw_failures
    from mergecraft.ci.normalize import normalize_failure

    branch = base_branch_from_event(ctx.gh_event)
    if branch is None:
        return BaseRunsCollection(note="no base branch in the event — base runs not read")
    lister = getattr(client, "list_workflow_runs_for_branch", None)
    if lister is None:
        return BaseRunsCollection(note="the SCM client cannot list base-branch runs")

    try:
        raw_failures = provider_jobs_to_raw_failures(jobs)
        fingerprint_by_run: dict[int, str] = {}
        for job, raw in zip(jobs, raw_failures, strict=False):
            run_id = job.get("job_id")
            if isinstance(run_id, int):
                fingerprint_by_run[run_id] = normalize_failure(raw)["failure_fingerprint"]
        workflows: dict[int, list[str]] = {}
        names: dict[int, str] = {}
        for run in current_runs:
            run_id = run.get("id")
            workflow_id = run.get("workflow_id")
            if (
                _conclusion(run) == "failure"
                and isinstance(run_id, int)
                and isinstance(workflow_id, int)
                and run_id in fingerprint_by_run
            ):
                workflows.setdefault(workflow_id, []).append(fingerprint_by_run[run_id])
                names[workflow_id] = str(run.get("name") or workflow_id)
        wanted = {fp for fps in workflows.values() for fp in fps}
        if not wanted:
            return BaseRunsCollection(note="no failing workflow run to compare against the base")

        rows: list[dict[str, Any]] = []
        downloads = 0
        for workflow_id in list(workflows)[:MAX_WORKFLOWS]:
            listed = await lister(ctx.repo.owner, ctx.repo.name, branch, workflow_id=workflow_id)
            completed = [
                run
                for run in listed.items
                if run.get("workflow_id") == workflow_id
                and str(run.get("status") or "completed") == "completed"
            ][:MAX_BASE_RUNS_PER_WORKFLOW]
            for position, run in enumerate(completed):
                conclusion = _conclusion(run)
                run_id = run.get("id")
                if not isinstance(run_id, int):
                    continue
                sha = str(run.get("head_sha") or "")
                base = {
                    "ref": f"{branch}@{sha[:7]}" if sha else branch,
                    "conclusion": conclusion,
                    "run_id": run_id,
                    "workflow": names[workflow_id],
                    "head_sha": sha,
                    "url": str(run.get("html_url") or ""),
                    "source": "auto",
                }
                if conclusion == "failure" and downloads < MAX_LOG_DOWNLOADS:
                    downloads += 1
                    archive = await client.download_workflow_run_logs(
                        ctx.repo.owner, ctx.repo.name, run_id
                    )
                    if not isinstance(archive, (bytes, bytearray)):
                        continue
                    from mergecraft.ci.providers.github_actions import GitHubActionsProvider

                    log_text = GitHubActionsProvider._decode_log_archive(archive)
                    fingerprint = _fingerprint_for_logs(names[workflow_id], run_id, log_text)
                    if fingerprint in wanted:
                        rows.append({**base, "fingerprint": fingerprint})
                elif conclusion == "success" and position == 0:
                    # The newest completed base run passed: recorded as (non-clearing)
                    # evidence against each failure of this workflow.
                    rows.extend({**base, "fingerprint": fp} for fp in workflows[workflow_id])
        return BaseRunsCollection(rows=rows)
    except Exception as err:  # base evidence is supplementary and never fails a review
        logger.warning("ci base-branch runs: could not be read — {}", err)
        return BaseRunsCollection(note=f"base-branch runs could not be read: {err}")


__all__ = ["BaseRunsCollection", "base_branch_from_event", "collect_base_branch_runs"]
