"""CLI regression-gate output names the moved metric (E-D3).

The PR check must invoke this path (``mergecraft eval gate --baseline
--candidate``). The formatter already lives in ``eval_gate_cmd``; this file
pins the exit code and the baseline / candidate / delta ledger so E2 cannot
swap in a bare ``make eval-gate`` bank-integrity call.
"""

from __future__ import annotations

from pathlib import Path

from tests.evals.support_eval_calibration import structural_baseline_path
from typer.testing import CliRunner

from mergecraft.cli.eval_cmd import app
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE
from mergecraft.evals.gate import eval_gate, load_result_set

runner = CliRunner()


def test_baseline_and_candidate_must_be_given_together() -> None:
    """Error: one of ``--baseline`` / ``--candidate`` without the other is rejected."""
    baseline = structural_baseline_path()
    result = runner.invoke(app, ["gate", "--baseline", str(baseline)])
    assert result.exit_code != 0
    blob = (result.output + result.stdout + result.stderr).casefold()
    assert "--baseline" in blob
    assert "--candidate" in blob


def test_regression_gate_failure_names_metric_and_ledger(tmp_path: Path) -> None:
    """A material regression exits non-zero and names metric + baseline/candidate/delta."""
    baseline = load_result_set(structural_baseline_path())
    bumped = min(1.0, baseline.metrics.unsafe_approval_rate + 0.25)
    candidate = baseline.model_copy(
        update={"metrics": baseline.metrics.model_copy(update={"unsafe_approval_rate": bumped})}
    )
    report = eval_gate(candidate=candidate, baseline=baseline)
    cand_path = tmp_path / "candidate.json"
    cand_path.write_text(candidate.model_dump_json(), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "gate",
            "--baseline",
            str(structural_baseline_path()),
            "--candidate",
            str(cand_path),
        ],
    )
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    output = result.output + result.stdout
    assert "unsafe_approval_rate" in output
    for metric in report.regressed_metrics:
        assert metric in output
    delta = next(item for item in report.deltas if item.metric == "unsafe_approval_rate")
    assert f"{delta.baseline:.2%}" in output or f"{delta.baseline}" in output
    assert f"{delta.candidate:.2%}" in output or f"{delta.candidate}" in output
    # Signed delta is printed as ``Δ +0.25%`` / ``(Δ …)`` by the existing CLI.
    assert "Δ" in output or "delta" in output.casefold()


def test_clean_regression_gate_exits_zero(tmp_path: Path) -> None:
    """Clean candidate against the published baseline is not a configuration failure."""
    baseline = load_result_set(structural_baseline_path())
    cand_path = tmp_path / "candidate.json"
    cand_path.write_text(baseline.model_dump_json(), encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "gate",
            "--baseline",
            str(structural_baseline_path()),
            "--candidate",
            str(cand_path),
        ],
    )
    assert result.exit_code == 0
    assert "unsafe_approval_rate" in (result.output + result.stdout)
