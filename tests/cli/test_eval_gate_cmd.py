"""``mergecraft eval gate`` — structural integrity of the eval bank (#51, C7)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from tests.evals.support_eval_calibration import structural_baseline_path
from typer.testing import CliRunner

from mergecraft.cli.eval_cmd import app
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE
from mergecraft.evals.gate import load_result_set

if TYPE_CHECKING:
    import pytest

runner = CliRunner()

_CASE = """---
id: {case_id}
title: a recorded failure
category: missed_finding
submitted_at: '2026-08-09T10:00:00+00:00'
run_id: synthetic
pr_number: 1
failure_mode: missed_finding
expected_finding: something
expected_decision: block
replay_command: mergecraft eval replay {case_id}
provenance:
  run_id: synthetic
  pr_number: 1
  source_field: eval_bank
  author_login: synthetic
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-09T10:00:00+00:00'
---

body
"""


def _write_case(bank: Path, case_id: str) -> None:
    bank.mkdir(parents=True, exist_ok=True)
    (bank / f"{case_id}.md").write_text(_CASE.format(case_id=case_id), encoding="utf-8")


def test_gate_passes_on_a_healthy_bank(tmp_path: Path) -> None:
    bank = tmp_path / "cases"
    _write_case(bank, "synthetic-001")

    result = runner.invoke(app, ["gate", "--bank", str(bank), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema_version"]
    assert payload["status"] == "pass"
    assert payload["loaded"] == 1


def test_gate_fails_on_an_unparsable_case(tmp_path: Path) -> None:
    """A durable case that no longer parses is silent rot — the gate's whole job."""
    bank = tmp_path / "cases"
    _write_case(bank, "synthetic-001")
    (bank / "broken.md").write_text("not a case file at all\n", encoding="utf-8")

    result = runner.invoke(app, ["gate", "--bank", str(bank), "--json"])

    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    payload = json.loads(result.stdout)
    assert payload["status"] == "fail"
    assert len(payload["broken"]) == 1


def test_gate_fails_on_duplicate_case_ids(tmp_path: Path) -> None:
    bank = tmp_path / "cases"
    _write_case(bank, "synthetic-001")
    (bank / "copy.md").write_text(_CASE.format(case_id="synthetic-001"), encoding="utf-8")

    result = runner.invoke(app, ["gate", "--bank", str(bank), "--json"])

    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert json.loads(result.stdout)["duplicates"]


def test_empty_bank_passes_but_says_it_measures_nothing(tmp_path: Path) -> None:
    bank = tmp_path / "cases"
    bank.mkdir()

    result = runner.invoke(app, ["gate", "--bank", str(bank)])

    assert result.exit_code == 0
    assert "not yet measuring anything" in result.output


def test_missing_bank_is_not_an_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["gate", "--bank", str(tmp_path / "absent")])

    assert result.exit_code == 0


def test_unpromoted_cases_only_fail_when_required(tmp_path: Path) -> None:
    bank = tmp_path / "cases"
    _write_case(bank, "synthetic-001")

    warned = runner.invoke(app, ["gate", "--bank", str(bank), "--json"])
    assert warned.exit_code == 0
    assert json.loads(warned.stdout)["unpromoted"] == ["synthetic-001"]

    required = runner.invoke(app, ["gate", "--bank", str(bank), "--require-promoted", "--json"])
    assert required.exit_code == CLI_CONFIGURATION_EXIT_CODE


def test_score_reports_recall_against_a_baseline(tmp_path: Path) -> None:
    actual = tmp_path / "actual.json"
    expected = tmp_path / "expected.jsonl"
    actual.write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "path": "src/a.py",
                        "start_line": 11,
                        "end_line": 12,
                        "severity": "Major",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    # JSON Lines, the shape a promoted baseline actually ships in.
    expected.write_text(
        json.dumps({"id": "x-1", "path": "src/a.py", "line_range": [10, 20], "severity": "high"})
        + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["score", str(actual), str(expected), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["recall"] == 1.0
    assert payload["matches"][0]["severity_agrees"] is True


def test_score_fails_below_the_required_recall(tmp_path: Path) -> None:
    actual = tmp_path / "actual.json"
    expected = tmp_path / "expected.json"
    actual.write_text(json.dumps({"findings": []}), encoding="utf-8")
    expected.write_text(
        json.dumps([{"id": "x-1", "path": "src/a.py", "line_range": [10, 20]}]),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["score", str(actual), str(expected), "--min-recall", "0.5"])

    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "below the required" in result.output


# ── release regression gate: coverage metrics + require-halves (EV1 → EV2) ──


def _baseline_with_detection(tmp_path: Path) -> Path:
    """The committed structural baseline with a detection half attached."""
    from mergecraft.evals.live_run import DetectionMetrics
    from mergecraft.evals.scoring import AggregateScoreReport

    baseline = load_result_set(structural_baseline_path())
    detection = DetectionMetrics(
        provider="claude",
        model="claude-sonnet-5",
        cases_run=2,
        cases_failed=0,
        failed_case_ids=[],
        aggregate=AggregateScoreReport(
            total_cases=1,
            total_issues=2,
            total_reported=2,
            found=1,
            false_negatives=1,
            unadjudicated=0,
            false_positives=1,
            false_positives_per_case=0.0,
            clean_case_fp_rate=0.0,
        ),
        case_results=[],
        raw_findings_dir="",
    )
    path = tmp_path / "baseline-with-detection.json"
    path.write_text(
        baseline.model_copy(update={"detection": detection}).model_dump_json(),
        encoding="utf-8",
    )
    return path


def test_gate_regression_names_inconclusive_rate_in_the_step_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A candidate with one added structural inconclusive exits non-zero and the
    step summary names ``inconclusive_rate`` with baseline / candidate / delta."""
    baseline = load_result_set(structural_baseline_path())
    bumped = baseline.metrics.inconclusive_rate + 0.25
    candidate = baseline.model_copy(
        update={"metrics": baseline.metrics.model_copy(update={"inconclusive_rate": bumped})}
    )
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(candidate.model_dump_json(), encoding="utf-8")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    result = runner.invoke(
        app,
        [
            "gate",
            "--baseline",
            str(structural_baseline_path()),
            "--candidate",
            str(candidate_path),
            "--bank",
            str(tmp_path / "absent-bank"),
        ],
    )

    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    text = summary.read_text(encoding="utf-8")
    assert "inconclusive_rate" in text
    assert f"{baseline.metrics.inconclusive_rate:.2%}" in text
    assert f"{bumped:.2%}" in text


def test_require_halves_flag_fails_a_candidate_missing_the_detection_half(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Release mode passes ``--require-halves``: a candidate missing the
    detection half the baseline carries fails, naming the missing half. Without
    the flag the PR check keeps today's skip."""
    baseline_path = _baseline_with_detection(tmp_path)
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(
        load_result_set(structural_baseline_path()).model_dump_json(), encoding="utf-8"
    )
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    common = [
        "gate",
        "--baseline",
        str(baseline_path),
        "--candidate",
        str(candidate_path),
        "--bank",
        str(tmp_path / "absent-bank"),
    ]

    skipped = runner.invoke(app, common)
    assert skipped.exit_code == 0, skipped.output

    required = runner.invoke(app, [*common, "--require-halves"])
    assert required.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "detection" in summary.read_text(encoding="utf-8")


def test_a_promoted_case_is_not_reported_as_unpromoted(tmp_path: Path) -> None:
    """The gate must ask the store for the path, not rebuild the filename."""
    from mergecraft.evals import permanent_test_path

    bank = tmp_path / "cases"
    _write_case(bank, "synthetic-001")
    permanent = tmp_path / "permanent"
    permanent.mkdir()
    permanent_test_path(permanent, "synthetic-001").write_text("# promoted\n", encoding="utf-8")

    import mergecraft.cli.eval_gate_cmd as eval_gate_cmd

    original = eval_gate_cmd.default_permanent_dir
    eval_gate_cmd.default_permanent_dir = lambda: permanent  # type: ignore[assignment,misc]
    try:
        result = runner.invoke(app, ["gate", "--bank", str(bank), "--require-promoted", "--json"])
    finally:
        eval_gate_cmd.default_permanent_dir = original  # type: ignore[assignment,misc]

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["unpromoted"] == []
