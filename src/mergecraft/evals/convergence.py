"""Multi-round convergence metric — first-pass recall and leakage rate (RC6).

Scores a PR reviewed over rounds ``1…N`` from ledger snapshots and recorded
findings. Matching reuses :func:`mergecraft.evals.scoring.score_findings` locality
overlap (±``DEFAULT_LINE_SLACK`` lines), not fingerprint equality.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, ConfigDict, Field

from mergecraft.analyzers.scope import line_intersects_hunks, parse_diff_scope
from mergecraft.evals.finding_rows import (
    baseline_issues_overlap,
    finding_line_bounds,
    finding_row_to_baseline,
    finding_row_to_reported,
    normalize_finding_path,
)
from mergecraft.evals.scoring import DEFAULT_LINE_SLACK, ReportedFinding, score_findings
from mergecraft.findings.ledger import (
    FindingLedger,  # noqa: TC001 — Pydantic arbitrary_types_allowed
)

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "ConvergenceCaseResult",
    "ConvergenceMetrics",
    "ConvergenceReport",
    "ConvergenceRound",
    "fold_convergence_reports",
    "score_convergence",
]

_SURFACED_STATES: Final[frozenset[str]] = frozenset({"open", "deferred"})


class ConvergenceRound(BaseModel):
    """One review round's ledger, findings, and first-reviewed diff."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    round_index: int
    ledger: FindingLedger
    findings: list[dict[str, Any]] = Field(default_factory=list)
    generated_fingerprints: list[str] = Field(default_factory=list)
    diff_text: str = ""


class ConvergenceReport(BaseModel):
    """Outcome of :func:`score_convergence` for one multi-round PR."""

    model_config = ConfigDict(extra="forbid")

    ground_truth_total: int
    ground_truth_fingerprints: list[str]
    ground_truth_attributable_to_round1: int
    round_one_attributable_fingerprints: list[str]
    first_pass_recall: float
    leakage_rate: float
    round_one_generated: int
    round_one_surfaced: int


class ConvergenceCaseResult(BaseModel):
    """One scenario's convergence outcome for corpus publication."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    report: ConvergenceReport


class ConvergenceMetrics(BaseModel):
    """Folded convergence metrics across a convergence eval corpus."""

    model_config = ConfigDict(extra="forbid")

    cases_total: int
    mean_first_pass_recall: float
    mean_leakage_rate: float
    case_results: list[ConvergenceCaseResult]


def _ledger_state(ledger: FindingLedger, fingerprint: str) -> str | None:
    record = ledger.get_record(fingerprint)
    return record.state if record is not None else None


def _is_surfaced(ledger: FindingLedger, fingerprint: str) -> bool:
    state = _ledger_state(ledger, fingerprint)
    return state in _SURFACED_STATES


def _round_by_index(
    rounds: Sequence[ConvergenceRound], round_index: int
) -> ConvergenceRound | None:
    for round_row in rounds:
        if round_row.round_index == round_index:
            return round_row
    return None


def _attributable_to_round1(
    finding: dict[str, Any],
    *,
    round_one_diff: str,
) -> bool:
    if not round_one_diff.strip():
        return True
    scope = parse_diff_scope(round_one_diff)
    path = normalize_finding_path(str(finding.get("path") or ""))
    start, end = finding_line_bounds(finding)
    return line_intersects_hunks(path, start, end, scope)


def _cluster_attributable_fingerprints(
    ground_truth_by_fp: dict[str, dict[str, Any]],
    attributable_fps: list[str],
    *,
    slack: int,
) -> list[str]:
    """Collapse locality-overlapping ground-truth rows to one canonical fingerprint."""
    canonical: list[str] = []
    for fingerprint in sorted(attributable_fps):
        candidate = finding_row_to_baseline(fingerprint, ground_truth_by_fp[fingerprint])
        if any(
            baseline_issues_overlap(
                finding_row_to_baseline(representative, ground_truth_by_fp[representative]),
                candidate,
                slack=slack,
            )
            for representative in canonical
        ):
            continue
        canonical.append(fingerprint)
    return canonical


def score_convergence(
    rounds: Sequence[ConvergenceRound],
    *,
    slack: int = DEFAULT_LINE_SLACK,
) -> ConvergenceReport:
    """Score first-pass recall and leakage from ledger snapshots alone."""
    ground_truth_by_fp: dict[str, dict[str, Any]] = {}
    for round_row in rounds:
        for finding in round_row.findings:
            fingerprint = str(finding.get("fingerprint") or "").strip()
            if fingerprint:
                ground_truth_by_fp.setdefault(fingerprint, finding)

    ground_truth_fingerprints = sorted(ground_truth_by_fp)
    round_one = _round_by_index(rounds, 1)
    round_one_diff = round_one.diff_text if round_one is not None else ""

    line_attributable = [
        fingerprint
        for fingerprint in ground_truth_fingerprints
        if _attributable_to_round1(
            ground_truth_by_fp[fingerprint],
            round_one_diff=round_one_diff,
        )
    ]
    round_one_attributable = _cluster_attributable_fingerprints(
        ground_truth_by_fp,
        line_attributable,
        slack=slack,
    )

    attributable_issues = [
        finding_row_to_baseline(fp, ground_truth_by_fp[fp]) for fp in round_one_attributable
    ]

    surfaced_findings: list[ReportedFinding] = []
    round_one_generated = 0
    round_one_surfaced = 0
    if round_one is not None:
        generated = list(round_one.generated_fingerprints)
        if not generated:
            generated = [
                str(row.get("fingerprint") or "").strip()
                for row in round_one.findings
                if str(row.get("fingerprint") or "").strip()
            ]
        round_one_generated = len(generated)
        finding_by_fp = {
            str(row.get("fingerprint") or "").strip(): row
            for row in round_one.findings
            if str(row.get("fingerprint") or "").strip()
        }
        for fingerprint in generated:
            if _is_surfaced(round_one.ledger, fingerprint):
                round_one_surfaced += 1
                row = finding_by_fp.get(fingerprint)
                if row is not None:
                    surfaced_findings.append(finding_row_to_reported(row))

    recall_report = score_findings(attributable_issues, surfaced_findings, slack=slack)
    leakage_rate = 0.0
    if round_one_generated > 0:
        leakage_rate = (round_one_generated - round_one_surfaced) / round_one_generated

    return ConvergenceReport(
        ground_truth_total=len(ground_truth_fingerprints),
        ground_truth_fingerprints=ground_truth_fingerprints,
        ground_truth_attributable_to_round1=len(round_one_attributable),
        round_one_attributable_fingerprints=round_one_attributable,
        first_pass_recall=recall_report.recall,
        leakage_rate=leakage_rate,
        round_one_generated=round_one_generated,
        round_one_surfaced=round_one_surfaced,
    )


def fold_convergence_reports(
    case_results: list[ConvergenceCaseResult],
) -> ConvergenceMetrics:
    """Fold per-case convergence reports into corpus-wide means."""
    total = len(case_results)
    if total == 0:
        return ConvergenceMetrics(
            cases_total=0,
            mean_first_pass_recall=1.0,
            mean_leakage_rate=0.0,
            case_results=[],
        )
    mean_recall = sum(row.report.first_pass_recall for row in case_results) / total
    mean_leakage = sum(row.report.leakage_rate for row in case_results) / total
    return ConvergenceMetrics(
        cases_total=total,
        mean_first_pass_recall=mean_recall,
        mean_leakage_rate=mean_leakage,
        case_results=case_results,
    )
