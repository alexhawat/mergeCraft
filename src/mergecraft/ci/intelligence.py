"""Orchestrate CI intelligence from provider output to review payload (K3 MCP seam)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from mergecraft.ci.providers.github_actions import GitHubActionsProvider

if TYPE_CHECKING:
    from mergecraft.ci.review import CiClusterReport, CiReviewStats
    from mergecraft.mcp.context import ToolContext

_COMMAND_HINT = re.compile(r"(make\s+\S+|uv run\s+\S+|pytest[^\n]*)")
_GITHUB_PROVIDER = GitHubActionsProvider()


def provider_jobs_to_raw_failures(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert ``get_check_suite_logs`` job rows to normalize-ready raw failures."""
    failures: list[dict[str, Any]] = []
    for job in jobs:
        excerpt = job.get("excerpt") or {}
        log_excerpt = str(excerpt.get("content") or "")
        command = ""
        for entry in job.get("log_index") or []:
            text = str(entry.get("content", ""))
            match = _COMMAND_HINT.search(text)
            if match:
                command = match.group(1)
                break
        if not command:
            match = _COMMAND_HINT.search(log_excerpt)
            if match:
                command = match.group(1)
        failures.append(
            {
                "job_name": job.get("job_name"),
                "job_id": job.get("job_id"),
                "step_name": "workflow",
                "command": command,
                "exit_code": 1,
                "log_excerpt": log_excerpt,
                "artifacts": [],
                "retry_state": None,
            }
        )
    return failures


def build_ci_intelligence_payload(
    reports: list[CiClusterReport],
    stats: CiReviewStats,
    overflow: int,
    *,
    raw_failures: list[dict[str, Any]] | None = None,
    fix_suggestions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the stable MCP/review payload from clustered CI intelligence."""
    from mergecraft.ci.review import (
        build_ci_pre_merge_summary,
        build_ci_review_comments,
        render_ci_failures_section,
    )

    clustered = [report.finding for report in reports]
    flaky_verdicts = {report.finding.fingerprint: report.flaky for report in reports}
    blame_verdicts = {report.finding.fingerprint: report.blame for report in reports}
    failure_excerpts = {report.finding.fingerprint: report.excerpt for report in reports}

    section = render_ci_failures_section(
        clustered,
        raw_failures=raw_failures,
        overflow=overflow,
        flaky_verdicts=flaky_verdicts,
        blame_verdicts=blame_verdicts,
        failure_excerpts=failure_excerpts,
    )
    comments = build_ci_review_comments(reports, fix_suggestions=fix_suggestions)
    return {
        "section": section,
        "preMergeSummary": build_ci_pre_merge_summary(stats),
        "comments": comments,
        "stats": {
            "failureCount": stats.failure_count,
            "clusterCount": stats.cluster_count,
            "flakyCount": stats.flaky_count,
            "prAttributedCount": stats.pr_attributed_count,
            "truncated": stats.truncated,
            "overflow": overflow,
        },
        "clusters": [
            {
                "fingerprint": report.finding.fingerprint,
                "message": report.finding.message,
                "flakyVerdict": report.flaky.classification,
                "flakySummary": report.flaky.summary,
                "blameVerdict": report.blame.attribution,
                "blameSummary": report.blame.summary,
                "affectedJobs": list(report.finding.evidence),
            }
            for report in reports
        ],
    }


def intelligence_from_failures(
    failures: list[dict[str, Any]],
    *,
    pr_diff_paths: list[str] | None = None,
    base_branch_runs: list[dict[str, Any]] | None = None,
    retry_attempts: dict[str, list[dict[str, Any]]] | None = None,
    base_branch_status: str | None = None,
    fix_suggestions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run the full CI intelligence pipeline on normalized/raw fixture failures."""
    from mergecraft.ci.review import analyze_ci_failures

    reports, stats, overflow = analyze_ci_failures(
        failures,
        pr_diff_paths=pr_diff_paths,
        base_branch_runs=base_branch_runs,
        retry_attempts=retry_attempts,
        base_branch_status=base_branch_status,
    )
    payload = build_ci_intelligence_payload(
        reports,
        stats,
        overflow,
        raw_failures=failures,
        fix_suggestions=fix_suggestions,
    )
    payload["available"] = bool(failures)
    return payload


async def run_ci_intelligence(
    ctx: ToolContext,
    *,
    check_suite_id: int,
    pr_diff_paths: list[str] | None = None,
    base_branch_runs: list[dict[str, Any]] | None = None,
    retry_attempts: dict[str, list[dict[str, Any]]] | None = None,
    base_branch_status: str | None = None,
    fix_suggestions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Fetch check-suite logs, analyze failures, and return review-ready CI intelligence."""
    from mergecraft.ci.review import analyze_ci_failures

    suite = await _GITHUB_PROVIDER.fetch_check_suite_logs(ctx, check_suite_id=check_suite_id)
    jobs = suite.get("jobs") or []
    provider_overflow = int(suite.get("overflow") or 0)
    total_failed_runs = int(suite.get("total_failed_runs") or len(jobs))
    if not jobs:
        reason = str(suite.get("message") or "no failed workflow runs found for this check suite")
        return {
            "available": False,
            "reason": reason,
            "section": "",
            "preMergeSummary": "",
            "comments": [],
            "stats": {
                "failureCount": 0,
                "clusterCount": 0,
                "flakyCount": 0,
                "prAttributedCount": 0,
                "truncated": False,
                "overflow": 0,
            },
            "clusters": [],
        }

    raw_failures = provider_jobs_to_raw_failures(jobs)
    reports, stats, overflow = analyze_ci_failures(
        raw_failures,
        pr_diff_paths=pr_diff_paths,
        base_branch_runs=base_branch_runs,
        retry_attempts=retry_attempts,
        base_branch_status=base_branch_status,
        total_failure_count=total_failed_runs,
        truncation_overflow=provider_overflow,
    )
    payload = build_ci_intelligence_payload(
        reports,
        stats,
        overflow,
        raw_failures=raw_failures,
        fix_suggestions=fix_suggestions,
    )
    payload["available"] = True
    payload["checkSuiteId"] = check_suite_id
    return payload


__all__ = [
    "build_ci_intelligence_payload",
    "intelligence_from_failures",
    "provider_jobs_to_raw_failures",
    "run_ci_intelligence",
]
