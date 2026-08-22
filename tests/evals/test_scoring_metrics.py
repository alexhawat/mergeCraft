"""F1, closed-world strict precision, and the FP ledger (#140, B1, RED wave).

`evals/scoring.py` currently reports recall/precision/severity_agreement only.
B1 extends `score_findings()`/`ScoreReport` with:

- `f1` — harmonic mean of recall and `corpus_confirmed_precision`, `0.0` (never
  `NaN`) when both are zero.
- `corpus_confirmed_precision` — the open-world-safe rename of today's
  `precision`; `precision` stays as a deprecated alias with the same value
  (D3: extend, never replace).
- `closed_world` — a per-call flag on `score_findings()` (there is no `Case`
  object in this module's flat issues/findings API, and a clean case has zero
  `BaselineIssue` rows to carry a per-issue flag, so the call site is the only
  place that can say "this corpus entry is fully labelled"). `ScoreReport`
  echoes it so `strict_precision` knows whether it is allowed to answer.
- `false_positives` / `unadjudicated` — the D5 three-state ledger. Unmatched
  findings are `false_positives` only when `closed_world=True`; otherwise they
  are `unadjudicated`, never asserted as noise (D4/D5).
- `strict_precision` — TP / (TP + false_positives), defined **only** on
  closed-world reports; raises on an open-world one (D4).
- `by_category` / `by_severity` — per-key breakdowns that sum back to the
  report's totals. Categories reuse `review_taxonomy.FINDING_CATEGORIES` (the
  finding-level taxonomy) — deliberately **not**
  `evals.benchmark.corpus_class_for()`'s four case-level buckets
  (`correctness`/`security`/`cross_file`/`adversarial_noop`), which classify a
  bank *case* for decision replay, not a finding's subject matter. See
  `docs/dev/test-plans/eval-benchmark-b1-metrics.md` for the reconciliation.

None of this exists yet — every test below is expected to fail (ImportError /
AttributeError) until B1.2 lands, except `test_score_report_still_forbids_
unknown_fields`, which exercises only today's shape and is a regression guard:
it already passes and must keep passing unchanged.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from mergecraft.evals.scoring import (
    BaselineIssue,
    ReportedFinding,
    ScoreReport,
    score_findings,
)
from mergecraft.review_taxonomy import FINDING_CATEGORIES, FINDING_SEVERITIES


def _issue(
    identifier: str = "b-1",
    *,
    path: str = "src/app.py",
    start: int = 10,
    end: int = 20,
    severity: str = "high",
    category: str = "",
) -> BaselineIssue:
    return BaselineIssue(
        id=identifier,
        path=path,
        start_line=start,
        end_line=end,
        severity=severity,
        category=category,
    )


def _finding(
    *,
    path: str = "src/app.py",
    start: int = 12,
    end: int = 14,
    severity: str = "Major",
    category: str = "",
) -> ReportedFinding:
    return ReportedFinding(
        path=path, start_line=start, end_line=end, severity=severity, category=category
    )


def _spaced_issue(index: int, *, path: str = "src/bench.py") -> BaselineIssue:
    """A baseline issue on its own 10-line block, far enough apart that the
    default ±3 line slack can never bleed into a neighbour."""
    line = index * 10 + 1
    return BaselineIssue(id=f"bench-{index:03d}", path=path, start_line=line, end_line=line + 1)


def _spaced_finding(index: int, *, path: str = "src/bench.py", offset: int = 0) -> ReportedFinding:
    line = offset + index * 10 + 1
    return ReportedFinding(path=path, start_line=line, end_line=line + 1)


# ── F1 — worked example (B1.1) ──────────────────────────────────────────────


def test_f1_matches_the_worked_example() -> None:
    """32 TP / 18 unadjudicated / 8 FN -> P 64.0%, R 80.0%, F1 71.1%."""
    issues = [_spaced_issue(i) for i in range(40)]
    matched_findings = [_spaced_finding(i) for i in range(32)]
    extra_findings = [_spaced_finding(i, offset=10_000) for i in range(18)]

    report = score_findings(issues, matched_findings + extra_findings)

    assert report.found == 32
    assert report.false_negatives == 8
    assert report.unadjudicated == 18
    assert report.false_positives == 0, "open-world: unmatched findings are never false_positives"
    assert report.recall == pytest.approx(0.8)
    assert report.corpus_confirmed_precision == pytest.approx(0.64)
    assert report.f1 == pytest.approx(0.711111, abs=1e-5)


def test_f1_is_zero_not_nan_when_precision_and_recall_are_both_zero() -> None:
    issues = [_issue(f"b-{i}", start=i * 100, end=i * 100 + 1) for i in range(3)]
    findings = [_finding(start=i * 100 + 900, end=i * 100 + 901) for i in range(2)]

    report = score_findings(issues, findings)

    assert report.recall == 0.0
    assert report.corpus_confirmed_precision == 0.0
    assert not math.isnan(report.f1)
    assert report.f1 == 0.0


def test_empty_corpus_is_vacuously_complete() -> None:
    report = score_findings([], [])

    assert report.recall == 1.0
    assert report.corpus_confirmed_precision == 1.0
    assert report.f1 == pytest.approx(1.0)
    assert report.severity_agreement is None
    assert report.false_negatives == 0
    assert report.unadjudicated == 0
    assert report.false_positives == 0


# ── closed-world ledger (D4/D5) ─────────────────────────────────────────────


def test_clean_case_zero_findings_has_strict_precision_one() -> None:
    report = score_findings([], [], closed_world=True)

    assert report.strict_precision == 1.0
    assert report.false_positives == 0
    assert report.unadjudicated == 0


def test_clean_case_with_false_findings_scores_strict_precision_zero() -> None:
    findings = [_finding(start=10, end=10), _finding(start=50, end=50)]

    report = score_findings([], findings, closed_world=True)

    assert report.strict_precision == 0.0
    assert report.false_positives == 2
    assert report.unadjudicated == 0, "closed-world unmatched findings are never unadjudicated"


def test_strict_precision_raises_on_an_open_world_report() -> None:
    report = score_findings([_issue()], [_finding()])  # closed_world defaults False

    with pytest.raises(ValueError, match=r"(?i)closed.world"):
        _ = report.strict_precision


def test_open_world_unmatched_findings_are_unadjudicated_not_false_positive() -> None:
    findings = [_finding(start=12, end=14), _finding(start=900, end=901)]

    report = score_findings([_issue()], findings)

    assert report.found == 1
    assert report.unadjudicated == 1
    assert report.false_positives == 0


# ── by_category / by_severity (B1.1) ────────────────────────────────────────


def test_by_category_and_by_severity_sum_back_to_the_totals() -> None:
    issues = [
        _issue("a", category="Functional Correctness", severity="Critical"),
        _issue("b", category="Functional Correctness", severity="Major", start=200, end=201),
        _issue("c", category="Security & Privacy", severity="Critical", start=400, end=401),
        _issue("d", category="Security & Privacy", severity="Minor", start=600, end=601),
    ]
    # Only "a" and "c" get a matching finding — "b" and "d" are missed.
    findings = [
        _finding(severity="Critical", start=10, end=20),
        _finding(severity="Critical", start=400, end=401),
    ]

    report = score_findings(issues, findings)

    assert sum(v.total_issues for v in report.by_category.values()) == report.total_issues
    assert sum(v.found for v in report.by_category.values()) == report.found
    assert sum(v.total_issues for v in report.by_severity.values()) == report.total_issues
    assert sum(v.found for v in report.by_severity.values()) == report.found

    assert report.by_category["Functional Correctness"].total_issues == 2
    assert report.by_category["Functional Correctness"].found == 1
    assert report.by_category["Security & Privacy"].total_issues == 2
    assert report.by_category["Security & Privacy"].found == 1


def test_by_category_keys_use_the_review_taxonomy_vocabulary() -> None:
    """by_category groups by review_taxonomy.FINDING_CATEGORIES — the
    finding-level taxonomy — never `corpus_class_for()`'s case-level buckets."""
    issues = [
        _issue(f"i-{i}", category=category, start=i * 100, end=i * 100 + 1)
        for i, category in enumerate(FINDING_CATEGORIES)
    ]

    report = score_findings(issues, [])

    assert set(report.by_category) == set(FINDING_CATEGORIES)
    for corpus_class in ("correctness", "security", "cross_file", "adversarial_noop"):
        assert corpus_class not in report.by_category


def test_by_severity_keys_use_the_normalized_finding_severities() -> None:
    issues = [
        _issue(f"s-{i}", severity=severity, start=i * 100, end=i * 100 + 1)
        for i, severity in enumerate(FINDING_SEVERITIES)
    ]

    report = score_findings(issues, [])

    assert set(report.by_severity) == set(FINDING_SEVERITIES)


# ── D3: deprecated alias (new contract — red until B1.2) ────────────────────


def test_existing_precision_alias_matches_corpus_confirmed_precision() -> None:
    """`precision` (D3: extended, never replaced) must still exist and equal
    the new canonical `corpus_confirmed_precision`."""
    report = score_findings([_issue()], [_finding(start=900, end=901)])

    assert report.precision == report.corpus_confirmed_precision


# ── D3 regression guard — passes today already, must keep passing ──────────


def test_score_report_still_forbids_unknown_fields() -> None:
    payload = score_findings([], []).model_dump()
    payload["bogus_field"] = True

    with pytest.raises(ValidationError):
        ScoreReport.model_validate(payload)
