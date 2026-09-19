"""E2 — versioned baseline, clean vs regressed demonstration, PR check summary.

Pins the DoD so E2/E6 can demonstrate: a deliberately regressed candidate
fails and names the metric; a clean one passes. ``load_result_set`` on the
committed baseline is reachable from a clean checkout (E-D2).

``format_pr_gate_summary`` is the E2 helper the check uses to state scope
and, on failure, each ``GateReport.regressed_metrics`` row with baseline /
candidate / delta. Lazy import keeps collection clean; the helper is RED
until E2.
"""

from __future__ import annotations

import subprocess

import pytest
from tests.ci.workflow_support import REPO_ROOT
from tests.evals.support_eval_calibration import STRUCTURAL_BASELINE, structural_baseline_path

from mergecraft.evals.gate import eval_gate, load_result_set


def _format_pr_gate_summary(report: object) -> str:
    from mergecraft.evals.gate import format_pr_gate_summary

    return format_pr_gate_summary(report)  # type: ignore[no-any-return]


def test_structural_baseline_is_versioned_and_loadable() -> None:
    """Committed baseline is on disk and parses as a result set."""
    path = structural_baseline_path()
    assert path.is_file(), f"missing versioned baseline {STRUCTURAL_BASELINE}"
    result = load_result_set(path)
    assert result.metrics.decision_replay_pass_rate >= 0.0
    assert result.case_results


def test_structural_baseline_is_tracked_in_git() -> None:
    """Reachable from a clean checkout — not gitignored, not local-only."""
    listed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--error-unmatch", STRUCTURAL_BASELINE],
        check=False,
        capture_output=True,
        text=True,
    )
    assert listed.returncode == 0, f"{STRUCTURAL_BASELINE} is not tracked"


def test_clean_committed_baseline_passes_eval_gate() -> None:
    """DoD — identical candidate vs the published baseline is not a regression."""
    baseline = load_result_set(structural_baseline_path())
    report = eval_gate(candidate=baseline, baseline=baseline)
    assert report.passed is True
    assert report.regressed_metrics == ()


def test_deliberately_regressed_baseline_fails_and_names_the_metric() -> None:
    """DoD — a material unsafe-approval rise fails and names that metric."""
    baseline = load_result_set(structural_baseline_path())
    bumped = min(1.0, baseline.metrics.unsafe_approval_rate + 0.25)
    candidate = baseline.model_copy(
        update={"metrics": baseline.metrics.model_copy(update={"unsafe_approval_rate": bumped})}
    )
    report = eval_gate(candidate=candidate, baseline=baseline)
    assert report.passed is False
    assert "unsafe_approval_rate" in report.regressed_metrics
    delta = next(item for item in report.deltas if item.metric == "unsafe_approval_rate")
    assert delta.baseline == baseline.metrics.unsafe_approval_rate
    assert delta.candidate == bumped
    assert delta.delta == bumped - baseline.metrics.unsafe_approval_rate
    assert delta.regressed is True


def test_pass_rate_drop_is_a_named_regression() -> None:
    """Direction-aware: a drop in ``decision_replay_pass_rate`` is named."""
    baseline = load_result_set(structural_baseline_path())
    dropped = max(0.0, baseline.metrics.decision_replay_pass_rate - 0.25)
    candidate = baseline.model_copy(
        update={
            "metrics": baseline.metrics.model_copy(update={"decision_replay_pass_rate": dropped})
        }
    )
    report = eval_gate(candidate=candidate, baseline=baseline)
    assert report.passed is False
    assert "decision_replay_pass_rate" in report.regressed_metrics
    assert "unsafe_approval_rate" not in report.regressed_metrics


def test_format_pr_gate_summary_states_structural_not_live_scope() -> None:
    """E-D3 — summary text says structural replay, not live detection quality."""
    baseline = load_result_set(structural_baseline_path())
    report = eval_gate(candidate=baseline, baseline=baseline)
    text = _format_pr_gate_summary(report).casefold()
    assert "structural replay" in text
    assert "live detection" in text
    assert "not" in text


def test_format_pr_gate_summary_names_regressed_metric_ledger() -> None:
    """On failure the summary names each metric plus baseline / candidate / delta."""
    baseline = load_result_set(structural_baseline_path())
    bumped = min(1.0, baseline.metrics.unsafe_approval_rate + 0.25)
    candidate = baseline.model_copy(
        update={"metrics": baseline.metrics.model_copy(update={"unsafe_approval_rate": bumped})}
    )
    report = eval_gate(candidate=candidate, baseline=baseline)
    text = _format_pr_gate_summary(report)
    assert "unsafe_approval_rate" in text
    delta = next(item for item in report.deltas if item.metric == "unsafe_approval_rate")
    assert _number_in_text(text, delta.baseline)
    assert _number_in_text(text, delta.candidate)
    assert _number_in_text(text, delta.delta)


def test_format_pr_gate_summary_requires_gate_report() -> None:
    """Error: a non-report argument is rejected with TypeError or ValueError."""
    from mergecraft.evals.gate import format_pr_gate_summary

    with pytest.raises((TypeError, ValueError)):
        format_pr_gate_summary("not-a-report")  # type: ignore[arg-type]


def _number_in_text(text: str, value: float) -> bool:
    """Accept raw, percent, or rounded renderings of a ledger float."""
    as_raw = f"{value}"
    as_fixed = f"{value:.2f}"
    as_pct = f"{value:.2%}"
    as_pct_short = f"{value * 100:.1f}"
    return any(token in text for token in (as_raw, as_fixed, as_pct, as_pct_short))


def test_gitignore_does_not_drop_the_published_baseline() -> None:
    """The published baseline stays reachable; only dated convergence dumps are ignored."""
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "evals/results/latest.json" not in gitignore
    assert "structural-replay-convergence-" in gitignore


def test_baseline_path_constant_matches_release_and_checkout() -> None:
    """The path CI/release cite is the same file ``load_result_set`` reads."""
    assert STRUCTURAL_BASELINE == "evals/results/latest.json"
    assert load_result_set(structural_baseline_path()) is not None
