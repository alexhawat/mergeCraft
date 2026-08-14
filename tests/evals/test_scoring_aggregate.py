"""AggregateScoreReport — folding many per-case ScoreReports (#140, B1, RED wave).

A single `score_findings()` call scores one case. #140's headline numbers
(false positives / case, clean-case FP rate, corpus-wide P/R/F1) are computed
over an entire corpus of cases, so B1.2 adds `fold_score_reports()` to reduce
many per-case `ScoreReport`s into one `AggregateScoreReport`.

Only `closed_world=True` cases can ever populate `false_positives` (D4), so
both `false_positives_per_case` and `clean_case_fp_rate` are averaged over the
closed-world subset only — an open-world case contributing a diluting zero
would make the metric drift with corpus composition rather than measure
anything. This is a design choice pinned here for B1.2; see
`docs/dev/test-plans/eval-benchmark-b1-metrics.md` for the rationale.

None of this exists yet — every test is expected to fail (AttributeError on
`scoring.fold_score_reports`, or TypeError on the new `closed_world` keyword)
until B1.2 lands.
"""

from __future__ import annotations

import pytest

# `fold_score_reports` does not exist yet (B1.2). Importing the module rather
# than the name keeps collection green — the AttributeError then surfaces
# inside each test body, as a real per-test failure, instead of aborting
# collection for the whole file.
from mergecraft.evals import scoring
from mergecraft.evals.scoring import BaselineIssue, ReportedFinding, ScoreReport, score_findings


def _clean_report(*, false_findings: int) -> ScoreReport:
    """A closed-world case with no baseline issues and ``false_findings`` bogus
    findings (0 -> a spotless run, >0 -> genuine false positives, D4)."""
    findings = [
        ReportedFinding(path="src/a.py", start_line=10 * i + 1, end_line=10 * i + 2)
        for i in range(false_findings)
    ]
    return score_findings([], findings, closed_world=True)


def _open_world_report() -> ScoreReport:
    issue = BaselineIssue(
        id="o-1",
        path="src/b.py",
        start_line=5,
        end_line=6,
        category="Security & Privacy",
        severity="Critical",
    )
    matched = ReportedFinding(path="src/b.py", start_line=5, end_line=6, severity="Critical")
    unadjudicated = ReportedFinding(path="src/b.py", start_line=900, end_line=901)
    return score_findings([issue], [matched, unadjudicated])


def test_fold_counts_every_report_as_one_case() -> None:
    reports = [
        _clean_report(false_findings=0),
        _clean_report(false_findings=2),
        _open_world_report(),
    ]

    aggregate = scoring.fold_score_reports(reports)

    assert aggregate.total_cases == 3


def test_fold_sums_totals_across_cases() -> None:
    reports = [
        _clean_report(false_findings=0),
        _clean_report(false_findings=2),
        _open_world_report(),
    ]

    aggregate = scoring.fold_score_reports(reports)

    assert aggregate.total_issues == sum(r.total_issues for r in reports)
    assert aggregate.total_reported == sum(r.total_reported for r in reports)
    assert aggregate.found == sum(r.found for r in reports)


def test_fold_false_positives_per_case_averages_over_closed_world_cases_only() -> None:
    # Two closed-world cases (0 and 2 false findings) + one open-world case that
    # must not dilute the denominator (D4: it cannot confirm a false positive).
    reports = [
        _clean_report(false_findings=0),
        _clean_report(false_findings=2),
        _open_world_report(),
    ]

    aggregate = scoring.fold_score_reports(reports)

    assert aggregate.false_positives_per_case == pytest.approx(1.0)  # (0 + 2) / 2


def test_fold_clean_case_fp_rate_is_the_fraction_of_closed_cases_with_a_false_finding() -> None:
    reports = [
        _clean_report(false_findings=0),
        _clean_report(false_findings=2),
        _open_world_report(),
    ]

    aggregate = scoring.fold_score_reports(reports)

    assert aggregate.clean_case_fp_rate == pytest.approx(0.5)  # 1 of 2 closed-world cases


def test_fold_of_zero_reports_does_not_divide_by_zero() -> None:
    aggregate = scoring.fold_score_reports([])

    assert aggregate.total_cases == 0
    assert aggregate.false_positives_per_case == 0.0
    assert aggregate.clean_case_fp_rate == 0.0
    assert aggregate.recall == 1.0
    assert aggregate.corpus_confirmed_precision == 1.0


def test_fold_by_category_sums_back_to_the_aggregate_totals() -> None:
    reports = [_clean_report(false_findings=0), _open_world_report()]

    aggregate = scoring.fold_score_reports(reports)

    assert sum(v.total_issues for v in aggregate.by_category.values()) == aggregate.total_issues
    assert sum(v.found for v in aggregate.by_category.values()) == aggregate.found


def test_fold_by_severity_sums_back_to_the_aggregate_totals() -> None:
    reports = [_clean_report(false_findings=0), _open_world_report()]

    aggregate = scoring.fold_score_reports(reports)

    assert sum(v.total_issues for v in aggregate.by_severity.values()) == aggregate.total_issues
    assert sum(v.found for v in aggregate.by_severity.values()) == aggregate.found
