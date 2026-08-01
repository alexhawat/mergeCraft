"""Review integration for clustered CI failures (K3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mergecraft.ci.blame import BlameVerdict, blame_failure
from mergecraft.ci.flaky import FlakyVerdict, classify_failure
from mergecraft.ci.truncate import DEFAULT_TRUNCATION_CAP, apply_truncation, truncation_notice
from mergecraft.ci.verification import annotate_caused_by_pr, annotate_not_caused_by_pr

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding

CI_SECTION_HEADING = "### 🚨 CI failures"
_EXCERPT_LINE_LIMIT = 12


@dataclass(frozen=True)
class CiReviewStats:
    """Counts surfaced in the pre-merge CI row (K3.2)."""

    failure_count: int
    cluster_count: int
    flaky_count: int
    pr_attributed_count: int
    truncated: bool


@dataclass(frozen=True)
class CiClusterReport:
    """One clustered root cause with classification verdicts."""

    finding: Finding
    flaky: FlakyVerdict
    blame: BlameVerdict
    excerpt: str


def _job_name_from_evidence(entry: str) -> str:
    return entry.split(":", 1)[0] if ":" in entry else entry


def _compact_excerpt(text: str, *, limit: int = _EXCERPT_LINE_LIMIT) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) <= limit:
        return "\n".join(lines)
    head = lines[: limit // 2]
    tail = lines[-(limit - len(head)) :]
    return "\n".join([*head, "…", *tail])


def _default_flaky(fingerprint: str) -> FlakyVerdict:
    return classify_failure(fingerprint=fingerprint, attempts=[], base_branch_runs=[])


def _default_blame(failure: dict[str, Any]) -> BlameVerdict:
    return blame_failure(
        failure=failure,
        pr_diff_paths=[],
        base_branch_status=None,
    )


def analyze_ci_failures(
    failures: list[dict[str, Any]],
    *,
    pr_diff_paths: list[str] | None = None,
    base_branch_runs: list[dict[str, Any]] | None = None,
    retry_attempts: dict[str, list[dict[str, Any]]] | None = None,
    base_branch_status: str | None = None,
    truncation_cap: int = DEFAULT_TRUNCATION_CAP,
    total_failure_count: int | None = None,
    truncation_overflow: int | None = None,
) -> tuple[list[CiClusterReport], CiReviewStats, int]:
    """Cluster, classify, and blame normalized/raw failures for review publishing."""
    from mergecraft.ci.cluster import cluster_failures
    from mergecraft.ci.normalize import normalize_failure

    if truncation_overflow is not None:
        analyzed_raw = failures
        overflow = truncation_overflow
    else:
        analyzed_raw, overflow = apply_truncation(failures, cap=truncation_cap)
    normalized = [normalize_failure(item) for item in analyzed_raw]
    clustered = cluster_failures(normalized)

    diff_paths = pr_diff_paths or []
    retry_attempts = retry_attempts or {}
    base_branch_runs = base_branch_runs or []

    reports: list[CiClusterReport] = []
    flaky_count = 0
    pr_attributed_count = 0

    normalized_by_fingerprint: dict[str, dict[str, Any]] = {}
    for item in normalized:
        normalized_by_fingerprint.setdefault(item["failure_fingerprint"], dict(item))

    for finding in clustered:
        fingerprint = finding.fingerprint
        representative: dict[str, Any] = normalized_by_fingerprint.get(
            fingerprint, dict(normalized[0])
        )
        flaky = classify_failure(
            fingerprint=fingerprint,
            attempts=retry_attempts.get(fingerprint, []),
            base_branch_runs=base_branch_runs,
        )
        blame = blame_failure(
            failure=representative,
            pr_diff_paths=diff_paths,
            base_branch_status=base_branch_status,
        )
        if flaky.classification == "flaky":
            flaky_count += 1
            finding = annotate_not_caused_by_pr(finding)
        elif blame.attribution == "caused_by_pr":
            pr_attributed_count += 1
            finding = annotate_caused_by_pr(finding)
        else:
            finding = annotate_not_caused_by_pr(finding)

        reports.append(
            CiClusterReport(
                finding=finding,
                flaky=flaky,
                blame=blame,
                excerpt=_compact_excerpt(str(representative.get("log_excerpt", ""))),
            )
        )

    stats = CiReviewStats(
        failure_count=total_failure_count if total_failure_count is not None else len(failures),
        cluster_count=len(reports),
        flaky_count=flaky_count,
        pr_attributed_count=pr_attributed_count,
        truncated=overflow > 0,
    )
    return reports, stats, overflow


def build_ci_pre_merge_summary(stats: CiReviewStats) -> str:
    """Build the Notes cell for the pre-merge CI row (K3.2)."""
    parts = [
        f"{stats.failure_count} failures",
        f"{stats.cluster_count} clusters",
        f"{stats.flaky_count} flaky",
        f"{stats.pr_attributed_count} PR-attributed",
    ]
    if stats.truncated:
        parts.append("truncated")
    return "; ".join(parts)


def render_ci_failures_section(
    clustered: list[Finding],
    *,
    raw_failures: list[dict[str, Any]] | None = None,
    overflow: int = 0,
    flaky_verdicts: dict[str, FlakyVerdict] | None = None,
    blame_verdicts: dict[str, BlameVerdict] | None = None,
    failure_excerpts: dict[str, str] | None = None,
) -> str:
    """Render the ``### 🚨 CI failures`` body section (K3.1)."""
    flaky_verdicts = flaky_verdicts or {}
    blame_verdicts = blame_verdicts or {}
    failure_excerpts = failure_excerpts or {}

    if not clustered and overflow <= 0:
        return ""

    lines = [CI_SECTION_HEADING, ""]
    if clustered:
        job_total = sum(len(item.evidence) for item in clustered)
        lines.append(
            f"{len(clustered)} root-cause cluster{'s' if len(clustered) != 1 else ''} "
            f"from {job_total} failing job{'s' if job_total != 1 else ''}."
        )
        lines.append("")
        for index, finding in enumerate(clustered, start=1):
            fingerprint = finding.fingerprint
            flaky = flaky_verdicts.get(fingerprint) or _default_flaky(fingerprint)
            blame = blame_verdicts.get(fingerprint) or _default_blame(
                {"log_excerpt": finding.message, "failure_fingerprint": fingerprint}
            )
            jobs = [_job_name_from_evidence(entry) for entry in finding.evidence]
            excerpt = failure_excerpts.get(fingerprint) or _compact_excerpt(finding.message)
            lines.extend(
                [
                    f"#### Cluster {index} — `{fingerprint}`",
                    "",
                    f"- **Root cause:** {finding.message}",
                    f"- **Flaky verdict:** {flaky.classification} — {flaky.summary}",
                    f"- **Blame verdict:** {blame.attribution} — {blame.summary}",
                    f"- **Affected jobs:** {', '.join(jobs) if jobs else 'unknown'}",
                    "- **Log excerpt:**",
                    "",
                    "```",
                    excerpt,
                    "```",
                    "",
                ]
            )
    elif raw_failures is not None:
        analyzed_count = len(raw_failures)
        total_runs = analyzed_count + overflow
        lines.append(f"CI reported {total_runs} failing runs; {analyzed_count} analyzed (cap).")
        lines.append("")

    notice = truncation_notice(overflow=overflow)
    if notice:
        lines.append(notice)
        lines.append("")

    return "\n".join(lines).rstrip()


def render_ci_failure_comment(failures: list[dict[str, Any]]) -> str:
    """Render an inline review comment body from normalized failures (K8/K3)."""
    if not failures:
        return ""
    representative = failures[0]
    excerpt = _compact_excerpt(str(representative.get("log_excerpt", "")))
    job = str(representative.get("job", "unknown"))
    step = str(representative.get("step", "unknown"))
    return f"CI step `{step}` in job `{job}` failed.\n\n```\n{excerpt}\n```"


def build_ci_review_comments(
    reports: list[CiClusterReport],
    *,
    fix_suggestions: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build inline review comments, attaching suggestions for contained hunks (K7/D19)."""
    fix_suggestions = fix_suggestions or {}
    comments: list[dict[str, Any]] = []
    for report in reports:
        if report.blame.attribution != "caused_by_pr" or report.blame.hunk is None:
            continue
        hunk = report.blame.hunk
        body = (
            f"_Stability & Availability_ | _{report.finding.severity}_ | _Quick win_ | _likely_\n\n"
            f"CI failure maps to this hunk — {report.flaky.summary}\n\n"
            f"**Blame:** {report.blame.summary}"
        )
        comment: dict[str, Any] = {
            "path": hunk.path,
            "line": hunk.line,
            "body": body,
        }
        suggestion = fix_suggestions.get(report.finding.fingerprint)
        if suggestion:
            comment["suggestion"] = suggestion
        comments.append(comment)
    return comments


__all__ = [
    "CI_SECTION_HEADING",
    "CiClusterReport",
    "CiReviewStats",
    "analyze_ci_failures",
    "build_ci_pre_merge_summary",
    "build_ci_review_comments",
    "render_ci_failure_comment",
    "render_ci_failures_section",
]
