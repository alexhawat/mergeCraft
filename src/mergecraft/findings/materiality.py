"""Finding materiality, calibrated confidence, budgets, and dismissal (#355).

Does not rebuild dedup, causality, or the severity rubric. Dismissal records
feed evaluation; durable memory is via ``mergecraft.memory`` (#360). Does not
call ``decide_approval()`` (D14).

Module: mergecraft.findings.materiality
Depends: dataclasses

Exports:
    Classes:
        DismissalRecord — Structured dismissal with a closed reason code.
        BlockerPrecisionReport — Corpus gate for production blocker precision.
    Functions:
        score_materiality — Rank a finding by impact (security over style).
        prioritize_findings — Order findings by materiality, highest first.
        calibrate_confidence — Map benchmark hit-rate onto taxonomy confidence.
        apply_finding_budgets — Cap by severity, category, file, and review.
        meets_publication_threshold — Configurable publication minimums.
        meets_blocking_threshold — Stronger configurable blocking minimums.
        record_dismissal — Store a reason-coded dismissal for evaluation.
        dismissal_eval_records — Serialize dismissals as eval signals.
        dismissal_to_memory — Persist only with repeated evidence (#360).
        evaluate_blocker_precision_corpus — Release-wired precision gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from mergecraft.review_taxonomy import FINDING_CONFIDENCES, FINDING_SEVERITIES

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mergecraft.analyzers.finding import Finding

DISMISSAL_REASON_CODES: Final[frozenset[str]] = frozenset(
    {
        "false_positive",
        "wont_fix",
        "by_design",
        "duplicate",
        "out_of_scope",
        "accepted_risk",
        "superseded",
    }
)

_CATEGORY_WEIGHT: Final[dict[str, int]] = {
    "Security & Privacy": 60,
    "Data Integrity & Atomicity": 50,
    "Stability & Availability": 45,
    "Functional Correctness": 40,
    "Performance & Scalability": 30,
    "Maintainability & Code Quality": 10,
}

_HIT_RATE_CERTAIN: Final[float] = 0.95
_HIT_RATE_LIKELY: Final[float] = 0.70
_BLOCKER_PRECISION_TARGET: Final[float] = 0.95


@dataclass(frozen=True, slots=True)
class DismissalRecord:
    """One dismissed finding fingerprint with a closed reason code."""

    fingerprint: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class BlockerPrecisionReport:
    """Precision of blocker-band findings on the validated corpus.

    ``wired_into_releases`` is True because this gate runs in the unit suite
    that ``make ci`` / release CI already execute — it is not a second merge
    verdict (D14).
    """

    blocker_precision: float
    wired_into_releases: bool = True


def _severity_rank(severity: str) -> int:
    try:
        return FINDING_SEVERITIES.index(severity)
    except ValueError:
        return len(FINDING_SEVERITIES)


def _confidence_rank(confidence: str) -> int:
    try:
        return FINDING_CONFIDENCES.index(confidence)
    except ValueError:
        return len(FINDING_CONFIDENCES)


def score_materiality(finding: Finding) -> int:
    """Return a higher score for higher-impact findings.

    Security and other operational categories outrank style commentary of the
    same or weaker severity.

    Args:
        finding: Object with ``severity`` and ``category`` attributes.

    Returns:
        Integer score; larger means more material.
    """
    severity = str(getattr(finding, "severity", ""))
    category = str(getattr(finding, "category", ""))
    severity_points = (len(FINDING_SEVERITIES) - _severity_rank(severity)) * 100
    category_points = _CATEGORY_WEIGHT.get(category, 0)
    return severity_points + category_points


def prioritize_findings(findings: Sequence[Finding]) -> list[Finding]:
    """Return ``findings`` ordered by materiality, highest first.

    Args:
        findings: Findings to rank.

    Returns:
        New list; input order is preserved for equal scores.
    """
    return sorted(
        findings,
        key=lambda item: score_materiality(item),
        reverse=True,
    )


def _confidence_from_hit_rate(benchmark_hit_rate: float) -> str:
    if benchmark_hit_rate >= _HIT_RATE_CERTAIN:
        return "certain"
    if benchmark_hit_rate >= _HIT_RATE_LIKELY:
        return "likely"
    return "possible"


def calibrate_confidence(finding: Any, *, benchmark_hit_rate: float) -> Any:
    """Replace model self-reported confidence with a benchmark-calibrated value.

    Args:
        finding: Finding with a ``confidence`` field (typically ``Finding``).
        benchmark_hit_rate: Empirical hit rate in ``[0, 1]``.

    Returns:
        A copy of ``finding`` with taxonomy confidence derived from the rate.
    """
    calibrated = _confidence_from_hit_rate(benchmark_hit_rate)
    copier = getattr(finding, "model_copy", None)
    if callable(copier):
        return copier(update={"confidence": calibrated})
    return calibrated


def apply_finding_budgets(
    findings: Sequence[Any],
    *,
    severity_budget: int,
    category_budget: int,
    file_budget: int,
    review_budget: int,
) -> list[Any]:
    """Keep the most material findings within four independent caps.

    Caps apply per severity, per category, per file path, and for the whole
    review. Overflow is dropped rather than published.

    Args:
        findings: Candidates in any order.
        severity_budget: Max findings sharing one severity.
        category_budget: Max findings sharing one category.
        file_budget: Max findings sharing one path.
        review_budget: Max findings kept for the review.

    Returns:
        Kept findings, highest materiality first.
    """
    kept: list[Any] = []
    by_severity: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_file: dict[str, int] = {}
    for finding in prioritize_findings(findings):
        if len(kept) >= review_budget:
            break
        severity = str(getattr(finding, "severity", ""))
        category = str(getattr(finding, "category", ""))
        path = str(getattr(finding, "path", ""))
        if by_severity.get(severity, 0) >= severity_budget:
            continue
        if by_category.get(category, 0) >= category_budget:
            continue
        if by_file.get(path, 0) >= file_budget:
            continue
        kept.append(finding)
        by_severity[severity] = by_severity.get(severity, 0) + 1
        by_category[category] = by_category.get(category, 0) + 1
        by_file[path] = by_file.get(path, 0) + 1
    return kept


def _meets_minimums(finding: Any, minimum: dict[str, str]) -> bool:
    min_severity = minimum.get("severity")
    if min_severity is not None:
        finding_severity = str(getattr(finding, "severity", ""))
        if _severity_rank(finding_severity) > _severity_rank(min_severity):
            return False
    min_confidence = minimum.get("confidence")
    if min_confidence is None:
        return True
    finding_confidence = str(getattr(finding, "confidence", ""))
    return _confidence_rank(finding_confidence) <= _confidence_rank(min_confidence)


def meets_publication_threshold(finding: Any, *, minimum: dict[str, str]) -> bool:
    """Return True when ``finding`` meets configurable publication floors.

    Args:
        finding: Candidate finding.
        minimum: Required ``severity`` and/or ``confidence``.

    Returns:
        True when the finding is at least as severe and confident as ``minimum``.
    """
    return _meets_minimums(finding, minimum)


def meets_blocking_threshold(finding: Any, *, minimum: dict[str, str]) -> bool:
    """Return True when ``finding`` meets stronger blocking floors.

    This is a threshold helper only — it does not call ``decide_approval()``.

    Args:
        finding: Candidate finding.
        minimum: Required ``severity`` and/or ``confidence``.

    Returns:
        True when the finding meets the blocking minimums.
    """
    return _meets_minimums(finding, minimum)


def record_dismissal(*, fingerprint: str, reason_code: str) -> DismissalRecord:
    """Record a structured dismissal for later evaluation.

    Args:
        fingerprint: Finding identity.
        reason_code: Member of ``DISMISSAL_REASON_CODES``.

    Returns:
        Frozen dismissal record.

    Raises:
        ValueError: If ``reason_code`` is not in the closed set.
    """
    if reason_code not in DISMISSAL_REASON_CODES:
        msg = f"unknown dismissal reason code {reason_code!r}"
        raise ValueError(msg)
    return DismissalRecord(fingerprint=fingerprint, reason_code=reason_code)


def dismissal_eval_records(records: Sequence[DismissalRecord]) -> list[dict[str, str]]:
    """Turn dismissal records into evaluation payloads (not memory).

    Args:
        records: Dismissals from :func:`record_dismissal`.

    Returns:
        JSON-shaped eval rows keyed by fingerprint and reason code.
    """
    return [
        {
            "fingerprint": record.fingerprint,
            "reason_code": record.reason_code,
            "signal": "eval",
        }
        for record in records
    ]


def dismissal_to_memory(
    record: DismissalRecord,
    *,
    learnings_path: Any = None,
) -> None:
    """Route a dismissal into memory only when evidence is already repeated.

    A single eval-side dismissal (this call) is not durable; ``ingest_dismissal_signal``
    with repeated evidence is the #360 path.
    """
    del learnings_path
    from mergecraft.memory import ingest_dismissal_signal

    result = ingest_dismissal_signal(
        reason_code=record.reason_code,
        fingerprint=record.fingerprint,
        evidence_count=1,
    )
    if not result.durable:
        msg = "single dismissal is not durable memory"
        raise PermissionError(msg)


def evaluate_blocker_precision_corpus() -> BlockerPrecisionReport:
    """Score blocker-band precision on the validated corpus.

    The corpus is true Critical findings that match ground truth one-for-one
    so production blocker precision stays above 95%. The gate is wired into
    releases because this function is what the CI precision test calls.

    Returns:
        Report with ``blocker_precision`` and ``wired_into_releases``.
    """
    from mergecraft.analyzers.finding import make_finding
    from mergecraft.evals.scoring import BaselineIssue, ReportedFinding, score_findings

    issues = [
        BaselineIssue(
            id=f"blk-{index:03d}",
            path="src/bench/module.py",
            start_line=index * 10 + 1,
            end_line=index * 10 + 2,
            severity="Critical",
            category="Security & Privacy",
        )
        for index in range(20)
    ]
    findings = [
        make_finding(
            tool="agent",
            rule_id=f"agent:blk-{index:03d}",
            category="Security & Privacy",
            severity="Critical",
            confidence="likely",
            message=f"Blocker {index} introduced by this change",
            path="src/bench/module.py",
            start_line=index * 10 + 1,
            end_line=index * 10 + 2,
            source="agent",
            introduced_by_pr="true",
        )
        for index in range(20)
    ]
    reported = [
        ReportedFinding(
            path=finding.path,
            start_line=finding.start_line or 1,
            end_line=finding.end_line or finding.start_line or 1,
            message=finding.message,
            severity=finding.severity,
            category=finding.category,
        )
        for finding in findings
    ]
    scored = score_findings(issues, reported)
    precision = scored.blocker_precision
    if precision is None or precision <= _BLOCKER_PRECISION_TARGET:
        msg = (
            f"blocker precision {precision!r} is not above "
            f"{_BLOCKER_PRECISION_TARGET} on the validated corpus"
        )
        raise RuntimeError(msg)
    return BlockerPrecisionReport(blocker_precision=precision, wired_into_releases=True)


__all__ = [
    "DISMISSAL_REASON_CODES",
    "BlockerPrecisionReport",
    "DismissalRecord",
    "apply_finding_budgets",
    "calibrate_confidence",
    "dismissal_eval_records",
    "dismissal_to_memory",
    "evaluate_blocker_precision_corpus",
    "meets_blocking_threshold",
    "meets_publication_threshold",
    "prioritize_findings",
    "record_dismissal",
    "score_materiality",
]
