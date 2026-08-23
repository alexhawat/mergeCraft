"""Convergence regression gate — recall + DG1 paired constraint (W10)."""

from __future__ import annotations

from pathlib import Path

from mergecraft.evals.benchmark import (
    BenchmarkMetrics,
    BenchmarkResultSet,
    GateMatrix,
    VersionPins,
)
from mergecraft.evals.convergence_benchmark import run_convergence_eval
from mergecraft.evals.gate import DEFAULT_GATE_TOLERANCE, eval_gate
from mergecraft.evals.store import DEFAULT_BANK_DIR


def _minimal_pins() -> VersionPins:
    return VersionPins.model_validate(
        {
            "rubric_version": "1.0.0",
            "judge_pins": {
                "claude": {
                    "provider": "claude",
                    "model": "claude-sonnet-5",
                    "model_pinned": True,
                    "judge_version": "1.1.0",
                    "rubric_version": "1.0.0",
                }
            },
            "mode_prompt_versions": {"stable": "abc"},
            "corpus_commit": "deadbeef",
            "recorded_at": "2026-08-22T20:00:00Z",
            "mergecraft_commit": "deadbeef",
            "mergecraft_version": "0.0.0",
            "reviewing_model": {
                "claude": {
                    "model_id": "claude-sonnet-5",
                    "model_pin": "claude-sonnet-5",
                    "model_pinned": True,
                }
            },
            "scorer_version": "1.0.0",
            "line_slack": 3,
        }
    )


def _empty_metrics() -> BenchmarkMetrics:
    return BenchmarkMetrics(
        cases_total=0,
        cases_replayable=0,
        cases_passed=0,
        cases_regression=0,
        cases_blocked=0,
        decision_replay_pass_rate=0.0,
        unsafe_approval_rate=0.0,
        clean_block_rate=0.0,
        inconclusive_rate=0.0,
        gate_matrix=GateMatrix(
            buggy_total=0,
            buggy_correct_block=0,
            buggy_unsafe_approval=0,
            buggy_inconclusive=0,
            clean_total=0,
            clean_correct_approval=0,
            clean_unsafe_block=0,
            clean_inconclusive=0,
        ),
        by_corpus_class={},
    )


def _convergence_result_set(tmp_path: Path) -> BenchmarkResultSet:
    result = run_convergence_eval(bank_dir=DEFAULT_BANK_DIR)
    return result.model_copy(update={"pins": _minimal_pins()})


def test_convergence_gate_passes_on_identical_result_sets(tmp_path: Path) -> None:
    baseline = _convergence_result_set(tmp_path)
    candidate = baseline.model_copy(deep=True)

    report = eval_gate(candidate=candidate, baseline=baseline, tolerance=DEFAULT_GATE_TOLERANCE)

    assert report.passed is True
    assert "convergence.mean_first_pass_recall" in {delta.metric for delta in report.deltas}
    assert "dg1.recall" in {delta.metric for delta in report.deltas}
    assert "dg1.corpus_confirmed_precision" in {delta.metric for delta in report.deltas}


def test_convergence_gate_fails_on_synthetic_recall_regression(tmp_path: Path) -> None:
    baseline = _convergence_result_set(tmp_path)
    assert baseline.convergence is not None
    regressed_case = baseline.convergence.case_results[0].model_copy(deep=True)
    regressed_report = regressed_case.report.model_copy(
        update={"first_pass_recall": 0.0},
    )
    regressed_cases = [
        regressed_case.model_copy(update={"report": regressed_report}),
        *baseline.convergence.case_results[1:],
    ]
    regressed_convergence = baseline.convergence.model_copy(
        update={
            "mean_first_pass_recall": 0.0,
            "case_results": regressed_cases,
        }
    )
    candidate = baseline.model_copy(update={"convergence": regressed_convergence})

    report = eval_gate(candidate=candidate, baseline=baseline, tolerance=0.0)

    assert report.passed is False
    assert "convergence.mean_first_pass_recall" in report.regressed_metrics
