"""Convergence benchmark replay — multi-round eval harness (RC6, W10)."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 — default args use Path at runtime
from typing import TYPE_CHECKING

import mergecraft
from mergecraft.agents.verifier import VERIFIER_RUBRIC_VERSION
from mergecraft.evals.benchmark import (
    DEFAULT_BENCHMARK_PROVIDERS,
    DEFAULT_RESULTS_DIR,
    SCORER_VERSION,
    BenchmarkMetrics,
    BenchmarkResultSet,
    GateMatrix,
    VersionPins,
    _judge_pins,
    _mode_prompt_versions,
    _reviewing_model_pins,
    write_result_set,
)
from mergecraft.evals.convergence import (
    PRE_W1_LEAKAGE_BASELINE_SCENARIO,
    ConvergenceCaseResult,
    build_pre_w1_leakage_round,
    fold_convergence_reports,
    score_convergence,
)
from mergecraft.evals.convergence_store import convergence_rounds_from_case, list_multi_round_cases
from mergecraft.evals.scoring import DEFAULT_LINE_SLACK
from mergecraft.evals.store import DEFAULT_BANK_DIR

if TYPE_CHECKING:
    from mergecraft.evals.convergence import ConvergenceRound


def _git_head_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _git_corpus_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD:evals/bank"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def load_convergence_scenarios(
    bank_dir: Path = DEFAULT_BANK_DIR,
    *,
    include_builtin_baseline: bool = False,
) -> list[tuple[str, list[ConvergenceRound]]]:
    """Load multi-round convergence scenarios from the eval bank (W10)."""
    scenarios: list[tuple[str, list[ConvergenceRound]]] = [
        (case.id, convergence_rounds_from_case(case)) for case in list_multi_round_cases(bank_dir)
    ]
    if include_builtin_baseline:
        scenarios.append((PRE_W1_LEAKAGE_BASELINE_SCENARIO, [build_pre_w1_leakage_round()]))
    return scenarios


def run_convergence_eval(
    scenarios: list[tuple[str, list[ConvergenceRound]]] | None = None,
    *,
    bank_dir: Path = DEFAULT_BANK_DIR,
    providers: tuple[str, ...] = DEFAULT_BENCHMARK_PROVIDERS,
    include_builtin_baseline: bool = False,
) -> BenchmarkResultSet:
    """Score multi-round scenarios and fold convergence metrics (RC6, W10)."""
    _assert_recall_pass_corpus_gate()
    if scenarios is None:
        scenarios = load_convergence_scenarios(
            bank_dir,
            include_builtin_baseline=include_builtin_baseline,
        )
    if not scenarios:
        scenarios = [(PRE_W1_LEAKAGE_BASELINE_SCENARIO, [build_pre_w1_leakage_round()])]
    case_results = [
        ConvergenceCaseResult(case_id=case_id, report=score_convergence(rounds))
        for case_id, rounds in scenarios
    ]
    convergence = fold_convergence_reports(case_results)
    metrics = BenchmarkMetrics(
        cases_total=convergence.cases_total,
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
    pins = VersionPins(
        rubric_version=VERIFIER_RUBRIC_VERSION,
        judge_pins=_judge_pins(providers),
        mode_prompt_versions=_mode_prompt_versions(),
        corpus_commit=_git_corpus_commit(),
        recorded_at=datetime.now(UTC),
        mergecraft_commit=_git_head_sha(),
        mergecraft_version=mergecraft.__version__,
        reviewing_model=_reviewing_model_pins(providers),
        scorer_version=SCORER_VERSION,
        line_slack=DEFAULT_LINE_SLACK,
    )
    return BenchmarkResultSet(
        pins=pins,
        metrics=metrics,
        case_results=[],
        convergence=convergence,
    )


def replay_convergence(
    *,
    bank_dir: Path = DEFAULT_BANK_DIR,
    results_dir: Path = DEFAULT_RESULTS_DIR,
    providers: tuple[str, ...] = DEFAULT_BENCHMARK_PROVIDERS,
    scenarios: list[tuple[str, list[ConvergenceRound]]] | None = None,
    include_builtin_baseline: bool = False,
) -> tuple[BenchmarkResultSet, Path]:
    """Run convergence eval and write a versioned result set under ``evals/results/``."""
    result = run_convergence_eval(
        scenarios,
        bank_dir=bank_dir,
        providers=providers,
        include_builtin_baseline=include_builtin_baseline,
    )
    path = write_result_set(result, results_dir=results_dir, update_latest=False)
    return result, path


def _assert_recall_pass_corpus_gate() -> None:
    """Fail closed when the recall-pass A/B corpus does not improve first-pass recall."""
    from mergecraft.evals.convergence import RECALL_PASS_W0_BASELINE, evaluate_recall_pass_corpus

    report = evaluate_recall_pass_corpus()
    if report.with_recall.mean_first_pass_recall <= report.without_recall.mean_first_pass_recall:
        msg = "recall-pass corpus gate failed: with-recall first-pass recall did not improve"
        raise ValueError(msg)
    if report.with_recall.mean_first_pass_recall <= RECALL_PASS_W0_BASELINE.mean_first_pass_recall:
        msg = "recall-pass corpus gate failed: with-recall first-pass recall below W0 baseline"
        raise ValueError(msg)


__all__ = [
    "load_convergence_scenarios",
    "replay_convergence",
    "run_convergence_eval",
]
