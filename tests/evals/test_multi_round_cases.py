"""Multi-round convergence bank cases (W10)."""

from __future__ import annotations

import pytest

from mergecraft.evals.convergence import score_convergence
from mergecraft.evals.convergence_benchmark import load_convergence_scenarios, run_convergence_eval
from mergecraft.evals.convergence_store import (
    CATEGORY_MULTI_ROUND_CONVERGENCE,
    convergence_rounds_from_case,
    list_multi_round_cases,
)
from mergecraft.evals.store import DEFAULT_BANK_DIR, load_case


def test_bank_carries_at_least_three_multi_round_cases() -> None:
    cases = list_multi_round_cases(DEFAULT_BANK_DIR)
    assert len(cases) >= 3
    assert all(case.category == CATEGORY_MULTI_ROUND_CONVERGENCE for case in cases)
    assert all(case.is_multi_round for case in cases)


@pytest.mark.parametrize(
    "case_id",
    [
        "pr-250-memory-feedback",
        "pr-253-scm-provider",
        "pr-216-eval-gate-matrix",
    ],
)
def test_multi_round_case_round_trips_and_scores(case_id: str) -> None:
    case = load_case(DEFAULT_BANK_DIR / f"{case_id}.md")
    assert len(case.rounds or []) >= 3
    rounds = convergence_rounds_from_case(case)
    assert len(rounds) == len(case.rounds)
    report = score_convergence(rounds)
    assert 0.0 <= report.first_pass_recall <= 1.0
    assert 0.0 <= report.leakage_rate <= 1.0
    for finding in case.rounds or []:
        for row in finding.findings:
            assert row.first_appeared_round >= 1


def test_load_convergence_scenarios_uses_bank_corpus() -> None:
    scenarios = load_convergence_scenarios(DEFAULT_BANK_DIR)
    assert len(scenarios) >= 3
    ids = {case_id for case_id, _ in scenarios}
    assert "pr-250-memory-feedback" in ids


def test_run_convergence_eval_folds_bank_cases() -> None:
    result = run_convergence_eval(bank_dir=DEFAULT_BANK_DIR)
    assert result.convergence is not None
    assert result.convergence.cases_total >= 3
    assert result.convergence.mean_first_pass_recall > 0.0
