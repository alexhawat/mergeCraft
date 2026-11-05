"""CI wiring for advisory eval rescore delta (#1164)."""

from __future__ import annotations

from pathlib import Path

from mergecraft.evals.rescore_delta import touches_reviewer_surface


def test_ci_workflow_mentions_eval_rescore_delta_job() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "eval-rescore-delta:" in text
    assert "ci_touches_reviewer_surface.py" in text


def test_reviewer_surface_helper_matches_modes_path() -> None:
    assert touches_reviewer_surface(["src/mergecraft/modes/Review.py"])


def test_rescore_script_avoids_clobbering_latest_json() -> None:
    text = Path("scripts/eval_rescore_delta_pr.sh").read_text(encoding="utf-8")
    assert "--no-update-latest" in text
    assert "mergecraft-eval-rescore" in text or "RUNNER_TEMP" in text


def test_rescore_delta_cli_prints_summary_on_stdout(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from mergecraft.cli.app import app
    from mergecraft.evals.benchmark import write_result_set
    from tests.evals.test_rescore_delta import _minimal_result

    runner = CliRunner()
    base_path = tmp_path / "base.json"
    head_path = tmp_path / "head.json"
    base_set = _minimal_result(commit="base", rows=[])
    head_set = _minimal_result(commit="head", rows=[])
    write_result_set(base_set, results_dir=tmp_path, filename="base.json", update_latest=False)
    write_result_set(head_set, results_dir=tmp_path, filename="head.json", update_latest=False)

    result = runner.invoke(
        app,
        [
            "eval",
            "rescore-delta",
            "--baseline",
            str(base_path),
            "--candidate",
            str(head_path),
            "--output",
            str(tmp_path / "delta.json"),
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Pass-rate" in result.stdout
    assert "Pass-rate" not in result.stderr or result.stdout.count("Pass-rate") >= 1
