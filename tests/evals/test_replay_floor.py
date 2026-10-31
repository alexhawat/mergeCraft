"""The structural replay bank has no permanently blocked case (#892).

Three multi-round convergence cases carried no single-round replay inputs, so
they replayed as ``blocked`` on every run and counted as inconclusive: a fixed
floor of 3/49 under ``inconclusive_rate`` regardless of behaviour. A gated rate
measured against a baseline that can never reach zero hides a real regression
inside the band it cannot fall below. Each case is now replayable (its first-round
reviewer findings are the recorded evidence) or, if one were ever removed from the
denominator, carries a recorded reason.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from tests.ci.workflow_support import REPO_ROOT

from mergecraft.evals.benchmark import run_structural_replay
from mergecraft.evals.convergence_store import convergence_rounds_from_case
from mergecraft.evals.store import DEFAULT_BANK_DIR, list_cases, load_case, replay_case

_CASES = ("pr-216-eval-gate-matrix", "pr-250-memory-feedback", "pr-253-scm-provider")


@pytest.mark.parametrize("case_id", _CASES)
def test_each_formerly_blocked_case_is_replayable(case_id: str) -> None:
    case = load_case(DEFAULT_BANK_DIR / f"{case_id}.md")

    assert case.is_replayable, f"{case_id} still carries no replay inputs"
    assert case.run_succeeded is True
    assert case.recorded_findings, "the recorded evidence is the first-round reviewer findings"


@pytest.mark.parametrize("case_id", _CASES)
def test_each_formerly_blocked_case_replays_to_its_expected_decision(case_id: str) -> None:
    case = load_case(DEFAULT_BANK_DIR / f"{case_id}.md")

    diff = replay_case(case, current_decision=None)

    assert diff.status == "passed", f"{case_id}: {diff}"
    assert diff.current_decision == case.expected_decision


@pytest.mark.parametrize("case_id", _CASES)
def test_the_replay_inputs_do_not_break_convergence_scoring(case_id: str) -> None:
    """The same case is still a multi-round convergence scenario."""
    case = load_case(DEFAULT_BANK_DIR / f"{case_id}.md")

    assert case.is_multi_round
    assert len(convergence_rounds_from_case(case)) >= 3


def test_the_bank_has_no_blocked_cases_and_no_hidden_floor() -> None:
    result = run_structural_replay()
    metrics = result.metrics

    assert metrics.cases_blocked == 0
    assert metrics.cases_replayable == metrics.cases_total
    genuinely_inconclusive = sum(
        1 for case in list_cases(DEFAULT_BANK_DIR) if not case.run_succeeded
    )
    assert metrics.inconclusive_rate == pytest.approx(genuinely_inconclusive / metrics.cases_total)
    assert metrics.unsafe_approval_rate == 0.0
    assert metrics.clean_block_rate == 0.0


def _committed() -> dict[str, Any]:
    loaded = json.loads((REPO_ROOT / "evals/results/latest.json").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_the_committed_baseline_was_regenerated_from_this_bank() -> None:
    committed = _committed()
    fresh = json.loads(run_structural_replay().model_dump_json())

    assert committed["metrics"] == fresh["metrics"]
    assert {row["case_id"]: row["status"] for row in committed["case_results"]} == {
        row["case_id"]: row["status"] for row in fresh["case_results"]
    }
    for row in committed["case_results"]:
        if row["case_id"] in _CASES:
            assert row["replayable"] is True
            assert row["status"] == "passed"
