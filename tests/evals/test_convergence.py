"""Multi-round convergence metric (RC6) — W4.1 RED suite.

Pins ``mergecraft.evals.convergence``: ground-truth union deduped by fingerprint,
first-pass recall (deferred counts as surfaced), leakage rate, and locality-based
matching via ``evals.scoring``'s ±3-line overlap rule. Implementation lands in W4.2.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.evals.scoring import DEFAULT_LINE_SLACK
from mergecraft.findings.ledger import FindingLedger
from mergecraft.findings.lifecycle import LifecycleState
from mergecraft.review_taxonomy import finding_fingerprint

if TYPE_CHECKING:
    from collections.abc import Sequence

_PATH = "src/app.py"

_ROUND1_DIFF = """\
diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,3 +10,6 @@ def handler():
     pass
+    timeout = None
+    return timeout
"""

_ROUND2_INCREMENTAL_DIFF = """\
diff --git a/src/app.py b/src/app.py
index 2222222..3333333 100644
--- a/src/app.py
+++ b/src/app.py
@@ -44,0 +45,5 @@
+def added_after_round_one():
+    pass
"""


def _convergence_mod() -> Any:
    return importlib.import_module("mergecraft.evals.convergence")


def _body(label: str) -> str:
    return f"{label} — convergence metric fixture."


def _fp(path: str, body: str) -> str:
    return finding_fingerprint(path=path, body=body)


def _finding(
    *,
    path: str = _PATH,
    start: int,
    end: int | None = None,
    body: str,
) -> dict[str, Any]:
    end_line = end if end is not None else start
    return {
        "fingerprint": _fp(path, body),
        "path": path,
        "start_line": start,
        "end_line": end_line,
        "body": body,
    }


def _ledger(*entries: tuple[str, LifecycleState, int]) -> FindingLedger:
    book = FindingLedger()
    for fingerprint, state, round_index in entries:
        book.record(fingerprint, state, source="test", round_index=round_index)
    return book


def _round(
    *,
    round_index: int,
    ledger: FindingLedger,
    findings: Sequence[dict[str, Any]],
    diff_text: str = "",
    generated_fingerprints: Sequence[str] | None = None,
) -> Any:
    convergence = _convergence_mod()
    generated = (
        list(generated_fingerprints)
        if generated_fingerprints is not None
        else [row["fingerprint"] for row in findings]
    )
    round_cls = convergence.ConvergenceRound
    return round_cls(
        round_index=round_index,
        ledger=ledger,
        findings=list(findings),
        generated_fingerprints=generated,
        diff_text=diff_text,
    )


def test_ground_truth_is_the_deduped_union_across_rounds() -> None:
    """Ground truth is the fingerprint-deduped union of findings from every round."""
    body_a = _body("missing timeout on retry")
    body_b = _body("unchecked null in handler")
    body_c = _body("race on shared cache")
    fp_a = _fp(_PATH, body_a)
    fp_b = _fp(_PATH, body_b)
    fp_c = _fp(_PATH, body_c)

    rounds = [
        _round(
            round_index=1,
            ledger=_ledger((fp_a, "open", 1), (fp_b, "deferred", 1)),
            findings=[
                _finding(start=12, body=body_a),
                _finding(start=18, body=body_b),
            ],
            diff_text=_ROUND1_DIFF,
        ),
        _round(
            round_index=2,
            ledger=_ledger((fp_a, "open", 2), (fp_c, "open", 2)),
            findings=[
                _finding(start=12, body=body_a),
                _finding(start=30, body=body_c),
            ],
            diff_text=_ROUND2_INCREMENTAL_DIFF,
        ),
    ]

    report = _convergence_mod().score_convergence(rounds)

    assert report.ground_truth_total == 3
    assert sorted(report.ground_truth_fingerprints) == sorted([fp_a, fp_b, fp_c])


def test_finding_about_code_added_by_the_fix_is_excluded_from_round_one_ground_truth() -> None:
    """Irreducible post-fix findings must not inflate the round-one recall denominator."""
    body_pre = _body("timeout never assigned")
    body_post = _body("new helper never tested")
    fp_pre = _fp(_PATH, body_pre)
    fp_post = _fp(_PATH, body_post)

    rounds = [
        _round(
            round_index=1,
            ledger=_ledger((fp_pre, "open", 1)),
            findings=[_finding(start=12, body=body_pre)],
            diff_text=_ROUND1_DIFF,
        ),
        _round(
            round_index=2,
            ledger=_ledger((fp_post, "open", 2)),
            findings=[_finding(start=46, body=body_post)],
            diff_text=_ROUND2_INCREMENTAL_DIFF,
        ),
    ]

    report = _convergence_mod().score_convergence(rounds)

    assert report.ground_truth_total == 2
    assert report.ground_truth_attributable_to_round1 == 1
    assert fp_post not in report.round_one_attributable_fingerprints
    assert fp_pre in report.round_one_attributable_fingerprints


def test_first_pass_recall_counts_deferred_findings_as_surfaced() -> None:
    """Deferral is disclosure — deferred round-one findings count toward recall."""
    body = _body("unchecked null before return")
    fingerprint = _fp(_PATH, body)

    rounds = [
        _round(
            round_index=1,
            ledger=_ledger((fingerprint, "deferred", 1)),
            findings=[_finding(start=12, body=body)],
            diff_text=_ROUND1_DIFF,
        ),
    ]

    report = _convergence_mod().score_convergence(rounds)

    assert report.ground_truth_attributable_to_round1 == 1
    assert report.first_pass_recall == pytest.approx(1.0)


def test_leakage_rate_is_zero_when_nothing_is_discarded() -> None:
    """Leakage is zero when every round-one generated finding is open or deferred."""
    body_open = _body("inline critical path")
    body_deferred = _body("overflowed major path")
    fp_open = _fp(_PATH, body_open)
    fp_deferred = _fp(_PATH, body_deferred)

    rounds = [
        _round(
            round_index=1,
            ledger=_ledger((fp_open, "open", 1), (fp_deferred, "deferred", 1)),
            findings=[
                _finding(start=12, body=body_open),
                _finding(start=14, body=body_deferred),
            ],
            generated_fingerprints=[fp_open, fp_deferred],
            diff_text=_ROUND1_DIFF,
        ),
    ]

    report = _convergence_mod().score_convergence(rounds)

    assert report.round_one_generated == 2
    assert report.round_one_surfaced == 2
    assert report.leakage_rate == pytest.approx(0.0)


def test_recall_uses_the_existing_location_overlap_rule() -> None:
    """Recall matches via ``score_findings`` ±3-line overlap, not fingerprint equality."""
    surfaced_body = _body("null deref near assignment")
    truth_body = _body("completely different wording for the same defect")
    fp_surfaced = _fp(_PATH, surfaced_body)
    fp_truth = _fp(_PATH, truth_body)
    assert fp_surfaced != fp_truth

    # Ground-truth anchor at 10-20; round-one surfaced anchor at 12-14 — within slack.
    assert 20 + DEFAULT_LINE_SLACK >= 12
    assert 10 - DEFAULT_LINE_SLACK <= 14

    rounds = [
        _round(
            round_index=1,
            ledger=_ledger((fp_surfaced, "open", 1)),
            findings=[_finding(start=12, end=14, body=surfaced_body)],
            diff_text=_ROUND1_DIFF,
        ),
        _round(
            round_index=2,
            ledger=_ledger((fp_truth, "open", 2)),
            findings=[_finding(start=10, end=20, body=truth_body)],
            diff_text=_ROUND2_INCREMENTAL_DIFF,
        ),
    ]

    report = _convergence_mod().score_convergence(rounds)

    assert report.ground_truth_attributable_to_round1 == 1
    assert report.first_pass_recall == pytest.approx(1.0)


def test_metric_is_computable_from_the_ledger_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """``score_convergence`` must not call live GitHub or SCM APIs."""
    body = _body("race when claiming row")
    fingerprint = _fp(_PATH, body)

    def _forbidden_github_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("score_convergence must not perform live GitHub calls")

    monkeypatch.setattr(
        "mergecraft.utils.github.get_issue_comment",
        _forbidden_github_call,
        raising=False,
    )

    rounds = [
        _round(
            round_index=1,
            ledger=_ledger((fingerprint, "deferred", 1)),
            findings=[_finding(start=12, body=body)],
            diff_text=_ROUND1_DIFF,
        ),
    ]

    report = _convergence_mod().score_convergence(rounds)

    assert report.ground_truth_attributable_to_round1 == 1
    assert report.first_pass_recall == pytest.approx(1.0)
    assert report.leakage_rate == pytest.approx(0.0)


def test_recall_pass_raises_first_pass_recall_on_the_corpus() -> None:
    """W7 gate — first-pass recall rises; DG1 precision corpus stays flat or better."""
    from mergecraft.evals.convergence import (
        evaluate_recall_pass_corpus,
        load_recall_pass_w0_baseline,
    )
    from mergecraft.findings.precision_corpus import (
        PRE_DG1_BASELINE,
        evaluate_dg1_precision_corpus,
    )

    report = evaluate_recall_pass_corpus()
    baseline = load_recall_pass_w0_baseline()

    assert report.with_recall.mean_first_pass_recall > report.without_recall.mean_first_pass_recall
    assert report.with_recall.mean_first_pass_recall > baseline.mean_first_pass_recall

    precision = evaluate_dg1_precision_corpus()
    assert precision.recall >= PRE_DG1_BASELINE.recall
    assert precision.corpus_confirmed_precision >= PRE_DG1_BASELINE.corpus_confirmed_precision
