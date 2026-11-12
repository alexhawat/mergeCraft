"""Base-vs-head structural rescore delta (#1164)."""

from __future__ import annotations

from datetime import UTC, datetime

from mergecraft.evals.benchmark import (
    BenchmarkMetrics,
    BenchmarkResultSet,
    CaseReplayRow,
    GateMatrix,
    ReviewingModelPin,
    VersionPins,
)
from mergecraft.evals.rescore_delta import compare_result_sets, touches_reviewer_surface
from mergecraft.evals.store import CASE_STATUS_PASSED, CASE_STATUS_REGRESSION


def _minimal_result(*, commit: str, rows: list[CaseReplayRow]) -> BenchmarkResultSet:
    now = datetime.now(UTC)
    metrics = BenchmarkMetrics(
        cases_total=len(rows),
        cases_replayable=len(rows),
        cases_passed=sum(1 for r in rows if r.status == CASE_STATUS_PASSED),
        cases_regression=sum(1 for r in rows if r.status == CASE_STATUS_REGRESSION),
        cases_blocked=0,
        decision_replay_pass_rate=0.5,
        unsafe_approval_rate=0.0,
        clean_block_rate=0.0,
        inconclusive_rate=0.0,
        by_corpus_class={},
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
    )
    pins = VersionPins(
        rubric_version="test",
        judge_pins={},
        mode_prompt_versions={},
        corpus_commit="abc",
        recorded_at=now,
        mergecraft_commit=commit,
        reviewing_model={
            "claude": ReviewingModelPin(model_id="m", model_pin="m", model_pinned=True),
        },
        scorer_version="1.0",
        line_slack=3,
    )
    return BenchmarkResultSet(pins=pins, metrics=metrics, case_results=rows)


def test_compare_result_sets_classifies_lost_pass() -> None:
    base = _minimal_result(
        commit="base",
        rows=[
            CaseReplayRow(
                case_id="a",
                corpus_class="correctness",
                status=CASE_STATUS_PASSED,
                expected_decision="block",
                current_decision="block",
                replayable=True,
            )
        ],
    )
    head = _minimal_result(
        commit="head",
        rows=[
            CaseReplayRow(
                case_id="a",
                corpus_class="correctness",
                status=CASE_STATUS_REGRESSION,
                expected_decision="block",
                current_decision="neutral",
                replayable=True,
            )
        ],
    )
    report = compare_result_sets(base, head)
    assert len(report.lost_pass) == 1
    assert report.lost_pass[0].case_id == "a"


def test_touches_reviewer_surface_detects_mode_changes() -> None:
    assert touches_reviewer_surface(["src/mergecraft/modes/Review.py"])
    assert not touches_reviewer_surface(["README.md"])


def test_rescore_delta_summary_includes_metric_lines() -> None:
    from mergecraft.evals.rescore_delta import format_rescore_summary

    base = _minimal_result(commit="base", rows=[])
    head = _minimal_result(commit="head", rows=[])
    report = compare_result_sets(base, head)
    text = format_rescore_summary(report)
    assert "Pass-rate" in text
    assert "Gained pass" in text
    assert "base" in text.lower() or "Base commit" in text


def test_decision_surface_paths_trigger_the_rescore_delta() -> None:
    """The one module that can move structural replay output must trigger the job."""
    from mergecraft.evals.rescore_delta import touches_reviewer_surface

    assert touches_reviewer_surface(["src/mergecraft/agents/gates.py"])
    assert touches_reviewer_surface(["src/mergecraft/findings/severity.py"])
    assert not touches_reviewer_surface(["src/mergecraft/agents/unrelated_module.py"])
