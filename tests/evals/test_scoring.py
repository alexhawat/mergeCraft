"""Locality-based ReviewBench scoring (#30, C7).

The point of these tests is that scoring must reward a run for *locating* a
baseline issue, and must not punish it for wording, rule ids, fingerprints, or a
severity vocabulary the corpus and the reviewer spell differently.
"""

from __future__ import annotations

from mergecraft.evals.scoring import (
    BaselineIssue,
    ReportedFinding,
    load_baseline_issues,
    load_reported_findings,
    normalize_severity,
    score_findings,
)


def _issue(
    identifier: str = "b-1",
    *,
    path: str = "src/app.py",
    start: int = 10,
    end: int = 20,
    severity: str = "high",
) -> BaselineIssue:
    return BaselineIssue(
        id=identifier, path=path, start_line=start, end_line=end, severity=severity
    )


def _finding(
    *,
    path: str = "src/app.py",
    start: int = 12,
    end: int = 14,
    severity: str = "Major",
    message: str = "totally different wording",
) -> ReportedFinding:
    return ReportedFinding(
        path=path, start_line=start, end_line=end, severity=severity, message=message
    )


def test_overlapping_finding_locates_the_issue_despite_different_wording() -> None:
    report = score_findings([_issue()], [_finding()])

    assert report.found == 1
    assert report.recall == 1.0
    assert report.missed_issue_ids == []


def test_finding_in_another_file_does_not_count() -> None:
    report = score_findings([_issue()], [_finding(path="src/other.py")])

    assert report.found == 0
    assert report.recall == 0.0
    assert report.missed_issue_ids == ["b-1"]
    assert report.unmatched_finding_indexes == [0]


def test_finding_far_from_the_issue_does_not_count() -> None:
    report = score_findings([_issue(start=10, end=20)], [_finding(start=900, end=901)])

    assert report.found == 0


def test_near_miss_within_slack_still_counts() -> None:
    # The reviewer anchored on the line just above the recorded range.
    report = score_findings([_issue(start=10, end=20)], [_finding(start=8, end=8)])

    assert report.found == 1


def test_one_finding_cannot_satisfy_two_issues() -> None:
    """A single sprawling comment must not score as locating everything."""
    issues = [_issue("b-1", start=10, end=12), _issue("b-2", start=10, end=12)]
    report = score_findings(issues, [_finding(start=10, end=12)])

    assert report.found == 1
    assert report.missed_issue_ids == ["b-2"]


def test_each_issue_claims_its_closest_finding() -> None:
    issues = [_issue("b-1", start=10, end=10), _issue("b-2", start=100, end=100)]
    findings = [_finding(start=100, end=100), _finding(start=10, end=10)]
    report = score_findings(issues, findings)

    assert report.found == 2
    by_issue = {m.issue_id: m.finding_index for m in report.matches}
    assert by_issue == {"b-1": 1, "b-2": 0}


def test_severity_vocabularies_are_reconciled() -> None:
    """`high` and `Major` are the same grade; the corpus itself proves it."""
    report = score_findings([_issue(severity="high")], [_finding(severity="Major")])

    assert report.matches[0].severity_agrees is True
    assert report.severity_agreement == 1.0


# ── maximum-cardinality matching (EV1 → EV2): recall cannot depend on order ──
#
# Counter-example with the default slack of 3 (``DEFAULT_LINE_SLACK``): issue A
# at line 10 and issue B at line 14; finding f0 at 12 overlaps both (distance 2
# to each) and finding f1 at 7 overlaps A only (distance 3). Greedy
# nearest-first lets A take f0, leaving B no candidate — recall 1/2, and 2/2
# when the issues are listed the other way round. Maximum matching recovers
# A to f1 and B to f0 for 2/2 in both orders.


def _contended_issues() -> list[BaselineIssue]:
    return [_issue("A", start=10, end=10), _issue("B", start=14, end=14)]


def _contended_findings() -> list[ReportedFinding]:
    return [_finding(start=12, end=12), _finding(start=7, end=7)]


def test_maximum_matching_recovers_the_later_issues_only_candidate() -> None:
    report = score_findings(_contended_issues(), _contended_findings())

    assert report.found == 2
    assert report.missed_issue_ids == []


def test_matching_is_order_independent_for_the_counter_example() -> None:
    """The same two issues in the opposite baseline order must score the same —
    recall cannot depend on the order the corpus happens to list them in."""
    forward = score_findings(_contended_issues(), _contended_findings())
    reverse = score_findings(list(reversed(_contended_issues())), _contended_findings())

    assert forward.found == 2
    assert reverse.found == 2


def test_matching_is_deterministic_across_repeated_calls() -> None:
    """EV-D4: candidates are tried in ``(distance, finding index)`` order, so the
    same inputs always yield the same issue→finding assignment."""
    first = score_findings(_contended_issues(), _contended_findings())
    second = score_findings(_contended_issues(), _contended_findings())

    assert [(match.issue_id, match.finding_index) for match in first.matches] == [
        (match.issue_id, match.finding_index) for match in second.matches
    ]


def test_severity_disagreement_is_reported_not_fatal() -> None:
    report = score_findings([_issue(severity="high")], [_finding(severity="Trivial")])

    assert report.found == 1, "a severity mismatch must not un-locate the issue"
    assert report.matches[0].severity_agrees is False


def test_precision_counts_only_corpus_confirmed_findings() -> None:
    report = score_findings(
        [_issue(start=10, end=20)],
        [_finding(start=12, end=14), _finding(start=800, end=801)],
    )

    assert report.recall == 1.0
    assert report.precision == 0.5


def test_empty_baseline_scores_as_vacuously_complete() -> None:
    report = score_findings([], [])

    assert report.recall == 1.0
    assert report.precision == 1.0
    assert report.severity_agreement is None


def test_normalize_severity_passes_unknown_grades_through() -> None:
    assert normalize_severity("high") == "Major"
    assert normalize_severity("MEDIUM") == "Minor"
    assert normalize_severity("") == ""
    assert normalize_severity("spicy") == "Spicy"


def test_loader_accepts_the_baseline_jsonl_row_shape() -> None:
    rows = [
        {
            "id": "x-1",
            "path": "src/a.py",
            "line_range": [5, 9],
            "severity": "high",
            "title": "t",
        }
    ]
    issues = load_baseline_issues(rows)

    assert issues[0].start_line == 5
    assert issues[0].end_line == 9


def test_loader_accepts_the_findings_envelope_shape() -> None:
    payload = {
        "findings": [{"path": "src/a.py", "start_line": 5, "end_line": 9, "severity": "Major"}]
    }
    findings = load_reported_findings(payload)

    assert findings[0].start_line == 5
    assert findings[0].severity == "Major"


def test_diff_prefixed_paths_match_plain_paths() -> None:
    report = score_findings([_issue(path="src/app.py")], [_finding(path="b/src/app.py")])

    assert report.found == 1


def test_inverted_line_range_is_tolerated() -> None:
    issues = load_baseline_issues([{"id": "x", "path": "p", "line_range": [20, 10]}])

    assert (issues[0].start_line, issues[0].end_line) == (10, 20)
