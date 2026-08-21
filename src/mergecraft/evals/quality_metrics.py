"""Quality metric set for defensible eval claims (#384).

Precision/recall/F1 publication belongs to #140. This module measures the
wider set: blocker precision, severity accuracy, duplicate / unsupported /
contradiction rates, time to first useful finding, P50/P95 latency, and
cost per review.

Reuses :func:`mergecraft.evals.scoring.score_findings` and
:func:`mergecraft.evals.benchmark.summarize_latencies` rather than
re-implementing locality matching or percentile math.

Exports:
    QualityMetrics: Named metric set for one scored review.
    compute_quality_metrics: Fold findings, baseline, and timing into QualityMetrics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from mergecraft.evals.scoring import (
    DEFAULT_LINE_SLACK,
    BaselineIssue,
    ReportedFinding,
    normalize_severity,
    score_findings,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["QualityMetrics", "compute_quality_metrics"]


class QualityMetrics(BaseModel):
    """The #384 quality metric set for one review (or folded sample)."""

    model_config = ConfigDict(extra="forbid")

    blocker_precision: float
    severity_accuracy: float
    duplicate_rate: float
    unsupported_finding_rate: float
    contradiction_rate: float
    time_to_first_useful_finding_ms: float | None
    p50_ms: float
    p95_ms: float
    cost_per_review: float


def _findings_overlap(first: ReportedFinding, second: ReportedFinding, *, slack: int) -> bool:
    """True when two findings share a path and their line spans touch within slack."""
    if first.path != second.path:
        return False
    return (
        second.start_line <= first.end_line + slack and first.start_line - slack <= second.end_line
    )


def _contradiction_rate(findings: Sequence[ReportedFinding], *, slack: int) -> float:
    """Fraction of findings that overlap an earlier finding at a different severity.

    ``0.0`` (never NaN) when nothing was reported.
    """
    if not findings:
        return 0.0
    contradictions = 0
    for index, finding in enumerate(findings):
        severity = normalize_severity(finding.severity)
        if any(
            _findings_overlap(earlier, finding, slack=slack)
            and normalize_severity(earlier.severity) != severity
            for earlier in findings[:index]
        ):
            contradictions += 1
    return contradictions / len(findings)


def compute_quality_metrics(
    *,
    findings: Sequence[ReportedFinding],
    baseline: Sequence[BaselineIssue],
    latencies_ms: Sequence[float],
    cost_usd: float,
    time_to_first_useful_finding_ms: float | None,
) -> QualityMetrics:
    """Score findings against a baseline and attach latency/cost.

    Empty findings yield ``0.0`` rates (honest-zero). An empty latency sample
    raises ``ValueError`` — a P50/P95 over nothing is never a fabricated 0.0.

    Args:
        findings: Reported review findings.
        baseline: Human-labelled expected issues.
        latencies_ms: Per-review (or per-stage) latencies in milliseconds.
        cost_usd: Cost attributed to this review in USD.
        time_to_first_useful_finding_ms: Wall time to the first baseline-matching
            finding, or ``None`` when none was useful.

    Returns:
        A :class:`QualityMetrics` row.

    Raises:
        ValueError: If ``latencies_ms`` is empty.
    """
    if not latencies_ms:
        msg = "latency sample is empty; P50/P95 need at least one duration"
        raise ValueError(msg)

    from mergecraft.evals.benchmark import summarize_latencies

    reported = list(findings)
    issues = list(baseline)
    scored = score_findings(issues, reported)
    summary = summarize_latencies(list(latencies_ms))
    unsupported = (
        0.0
        if scored.total_reported == 0
        else len(scored.unmatched_finding_indexes) / scored.total_reported
    )
    return QualityMetrics(
        blocker_precision=(1.0 if scored.blocker_precision is None else scored.blocker_precision),
        severity_accuracy=scored.severity_agreement,
        duplicate_rate=scored.duplicate_rate,
        unsupported_finding_rate=unsupported,
        contradiction_rate=_contradiction_rate(reported, slack=DEFAULT_LINE_SLACK),
        time_to_first_useful_finding_ms=time_to_first_useful_finding_ms,
        p50_ms=summary.p50_ms,
        p95_ms=summary.p95_ms,
        cost_per_review=cost_usd,
    )
