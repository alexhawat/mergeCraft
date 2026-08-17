"""EV2 — judge value: noise removed and recall lost are both reported.

RED suite for PR EV2 (sub-wave EV2.1; implementation EV2.2). Wave plan:
``.ignorelocal/waves/04-observability-eval-wave-plan.md``; test-plan doc:
``docs/test-plans/04-observability-eval.md``.

A judge (a second-pass filter over raw findings) that improves precision only
by destroying recall must **look bad** (plan §EV2.1). The pinned contract is a
pure before/after comparison over two closed-world ``ScoreReport``\\ s — the
pre-judge and post-judge scorings of the same run:

- ``JudgeValue`` (new model in ``evals/scoring.py``):
  ``noise_removed: int`` (false positives the judge filtered out) and
  ``recall_lost: int`` (baseline issues the pre-judge run located that the
  post-judge run no longer does).
- ``judge_value(before, after) -> JudgeValue``.

Both symbols are imported lazily inside the test (ImportError at RED time;
collection stays clean). Keyless and pure: ``skipped: no live gate``.

Reconciled post-EV2.2 (2026-08-17): EV2.2 (commit ``3d64488``) made all tests
in this file XPASS; the non-strict ``green after EV2.2`` xfail markers were
removed, so every test here is now a clean real pass.

"""

from __future__ import annotations

import pytest

from mergecraft.evals.scoring import (
    BaselineIssue,
    ReportedFinding,
    score_findings,
)


def _issue(identifier: str, *, start: int) -> BaselineIssue:
    return BaselineIssue(id=identifier, path="src/app.py", start_line=start, end_line=start + 1)


def _finding(*, start: int, path: str = "src/app.py") -> ReportedFinding:
    return ReportedFinding(path=path, start_line=start, end_line=start + 1)


def test_noise_removed_and_recall_lost_are_both_reported() -> None:
    """The judge filters two real false positives *and* one true finding:
    strict precision improves (2/4 -> 1/1) while recall drops — both halves of
    that trade must be reported, or the judge looks like a pure win."""
    from mergecraft.evals.scoring import judge_value

    issues = [_issue("iss-a", start=10), _issue("iss-b", start=110)]
    before = score_findings(
        issues,
        [
            _finding(start=10),  # matches iss-a
            _finding(start=110),  # matches iss-b
            _finding(start=50, path="src/other.py"),  # false positive
            _finding(start=70, path="src/third.py"),  # false positive
        ],
        closed_world=True,
    )
    after = score_findings(
        issues,
        [_finding(start=10)],  # the judge kept only the iss-a finding
        closed_world=True,
    )

    assert before.strict_precision == pytest.approx(0.5)
    assert after.strict_precision == pytest.approx(1.0)

    value = judge_value(before, after)

    assert value.noise_removed == 2
    assert value.recall_lost == 1
