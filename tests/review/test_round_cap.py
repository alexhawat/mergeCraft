"""Review round cap (#1166)."""

from __future__ import annotations

from mergecraft.agents.gates import decide_approval
from mergecraft.config.settings import RepoSettings, ReviewSettings
from mergecraft.review.round_cap import (
    max_review_rounds,
    review_round_cap_exceeded,
    round_cap_findings_for_run,
)


def test_under_at_over_cap_boundaries() -> None:
    cap = 3
    assert not review_round_cap_exceeded(round_index=2, cap=cap)
    assert not review_round_cap_exceeded(round_index=3, cap=cap)
    assert review_round_cap_exceeded(round_index=4, cap=cap)


def test_cap_finding_only_once() -> None:
    settings = RepoSettings(review=ReviewSettings(max_review_rounds=3))
    first = round_cap_findings_for_run(round_index=4, settings=settings, already_posted=False)
    second = round_cap_findings_for_run(round_index=4, settings=settings, already_posted=True)
    assert len(first) == 1
    assert second == []


def test_cap_finding_never_produces_approval() -> None:
    settings = RepoSettings(review=ReviewSettings(max_review_rounds=3))
    finding = round_cap_findings_for_run(round_index=5, settings=settings, already_posted=False)[0]
    assert finding.introduced_by_pr == "true"
    verdict = decide_approval([finding], run_succeeded=True, tier="trusted")
    assert verdict == "failure"


def test_zero_cap_disables() -> None:
    settings = RepoSettings(review=ReviewSettings(max_review_rounds=0))
    assert max_review_rounds(settings) == 0
    assert round_cap_findings_for_run(round_index=99, settings=settings, already_posted=False) == []
