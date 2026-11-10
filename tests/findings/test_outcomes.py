"""Human finding outcomes classifier (#1165)."""

from __future__ import annotations

from mergecraft.findings.outcomes import (
    FindingOutcomeReport,
    classify_pull_request_outcomes,
    classify_thread_outcome,
    summarize_outcomes,
)

_MERGEcraft_MARKER = "<!-- mergecraft-finding:v1:abc123def456 -->\n*via mergecraft*"


def _production_thread(
    *,
    thread_id: str = "PRRT_kwDOExample123",
    body: str = _MERGEcraft_MARKER,
    human_reply: str | None = None,
    resolved: bool = False,
    outdated: bool = False,
) -> dict[str, object]:
    """Shape from ``fetch_review_threads`` (``threadId``, not ``id``)."""
    comments: list[dict[str, object]] = [
        {
            "author": "mergecraft[bot]",
            "body": body,
            "path": "a.py",
            "line": 1,
        }
    ]
    if human_reply is not None:
        comments.append({"author": "human", "body": human_reply})
    return {
        "threadId": thread_id,
        "isResolved": resolved,
        "isOutdated": outdated,
        "comments": comments,
    }


def test_resolved_thread_is_fixed() -> None:
    thread = _production_thread(resolved=True)
    outcome, _reason = classify_thread_outcome(
        thread, publishers=frozenset({"mergecraft[bot]"}), merged=True
    )
    assert outcome == "fixed"


def test_human_rejection() -> None:
    thread = _production_thread(human_reply="This is wrong — not valid.")
    outcome, _reason = classify_thread_outcome(
        thread, publishers=frozenset({"mergecraft[bot]"}), merged=False
    )
    assert outcome == "rejected"


def test_false_positive_is_rejected_not_intentional() -> None:
    thread = _production_thread(human_reply="False positive — not an issue here.")
    outcome, _reason = classify_thread_outcome(
        thread, publishers=frozenset({"mergecraft[bot]"}), merged=False
    )
    assert outcome == "rejected"


def test_not_a_bug_is_rejected() -> None:
    thread = _production_thread(human_reply="Not a bug; working as designed for v1.")
    outcome, reason = classify_thread_outcome(
        thread, publishers=frozenset({"mergecraft[bot]"}), merged=False
    )
    assert outcome == "rejected"
    assert "rejected" in reason


def test_wont_fix_is_intentional() -> None:
    thread = _production_thread(human_reply="Won't fix — intentional for this release.")
    outcome, _reason = classify_thread_outcome(
        thread, publishers=frozenset({"mergecraft[bot]"}), merged=False
    )
    assert outcome == "intentional"


def test_merged_with_open_thread_is_ignored() -> None:
    thread = _production_thread()
    outcome, _reason = classify_thread_outcome(
        thread, publishers=frozenset({"mergecraft[bot]"}), merged=True
    )
    assert outcome == "ignored"


def test_open_thread_on_unmerged_pr_is_unknown_not_ignored() -> None:
    thread = _production_thread()
    outcome, reason = classify_thread_outcome(
        thread, publishers=frozenset({"mergecraft[bot]"}), merged=False
    )
    assert outcome == "unknown"
    assert "not merged" in reason


def test_report_preserves_production_thread_id() -> None:
    thread = _production_thread(thread_id="PRRT_kwDOExample456")
    report = classify_pull_request_outcomes(
        pull_number=7,
        threads=[thread],
        publishers=frozenset({"mergecraft[bot]"}),
        merged=False,
    )
    assert len(report.rows) == 1
    assert report.rows[0].thread_id == "PRRT_kwDOExample456"
    assert report.rows[0].outcome == "unknown"


def test_outdated_unresolved_thread_is_stale_not_fixed() -> None:
    thread = _production_thread(outdated=True)
    outcome, reason = classify_thread_outcome(
        thread, publishers=frozenset({"mergecraft[bot]"}), merged=True
    )
    assert outcome == "stale"
    assert "outdated" in reason


def test_resolved_and_outdated_thread_is_still_fixed() -> None:
    thread = _production_thread(resolved=True, outdated=True)
    outcome, _reason = classify_thread_outcome(
        thread, publishers=frozenset({"mergecraft[bot]"}), merged=True
    )
    assert outcome == "fixed"


def test_stale_counts_in_rates_without_inflating_fixed() -> None:
    report = classify_pull_request_outcomes(
        pull_number=7,
        threads=[_production_thread(outdated=True)],
        publishers=frozenset({"mergecraft[bot]"}),
        merged=True,
    )
    rates = report.rates()
    assert rates["stale"] == 1.0
    assert rates["fixed"] == 0.0


def _report(pull: int, *threads: dict[str, object], merged: bool = True) -> FindingOutcomeReport:
    return classify_pull_request_outcomes(
        pull_number=pull,
        threads=list(threads),
        publishers=frozenset({"mergecraft[bot]"}),
        merged=merged,
    )


def test_summary_aggregates_rates_across_pull_requests() -> None:
    summary = summarize_outcomes(
        [
            _report(1, _production_thread(resolved=True)),
            _report(2, _production_thread(human_reply="false positive")),
            _report(3, _production_thread(), merged=False),
        ]
    )
    assert summary.advisory is True
    assert summary.pulls == [1, 2, 3]
    assert summary.counts["fixed"] == 1
    assert summary.counts["rejected"] == 1
    assert summary.counts["unknown"] == 1
    assert summary.rates["fixed"] == 0.5
    assert summary.rates["rejected"] == 0.5
    assert "unknown" not in summary.rates
    assert summary.known_clean_pulls == []
    assert summary.clean_pull_findings_per_pull is None


def test_every_finding_on_a_known_clean_pr_is_a_false_positive() -> None:
    """A clean PR's finding counts even when the thread was resolved, not rejected."""
    summary = summarize_outcomes(
        [
            _report(10, _production_thread(resolved=True), _production_thread(thread_id="t2")),
            _report(11),
            _report(12, _production_thread(resolved=True)),
        ],
        known_clean_pulls=[10, 11],
    )
    assert summary.known_clean_pulls == [10, 11]
    assert summary.clean_pull_findings == 2
    assert summary.clean_pull_findings_per_pull == 1.0


def test_a_declared_clean_pr_that_was_not_reported_does_not_dilute_the_check() -> None:
    summary = summarize_outcomes(
        [_report(10, _production_thread(resolved=True))],
        known_clean_pulls=[10, 99],
    )
    assert summary.known_clean_pulls == [10]
    assert summary.clean_pull_findings_per_pull == 1.0


def test_summary_lists_incomplete_pulls() -> None:
    report = classify_pull_request_outcomes(
        pull_number=4,
        threads=[_production_thread()],
        publishers=frozenset({"mergecraft[bot]"}),
        merged=True,
        incomplete=True,
    )
    assert summarize_outcomes([report]).incomplete_pulls == [4]
