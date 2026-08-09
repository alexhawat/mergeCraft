"""``mergecraft eval gate`` — structural integrity of the eval bank (#51, C7)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from mergecraft.cli.eval_cmd import app

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
    assert payload["status"] == "pass"
    assert payload["loaded"] == 1


def test_gate_fails_on_an_unparsable_case(tmp_path: Path) -> None:
    """A durable case that no longer parses is silent rot — the gate's whole job."""
    bank = tmp_path / "cases"
    _write_case(bank, "synthetic-001")
    (bank / "broken.md").write_text("not a case file at all\n", encoding="utf-8")

    result = runner.invoke(app, ["gate", "--bank", str(bank), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "fail"
    assert len(payload["broken"]) == 1


def test_gate_fails_on_duplicate_case_ids(tmp_path: Path) -> None:
    bank = tmp_path / "cases"
    _write_case(bank, "synthetic-001")
    (bank / "copy.md").write_text(_CASE.format(case_id="synthetic-001"), encoding="utf-8")

    result = runner.invoke(app, ["gate", "--bank", str(bank), "--json"])

    assert result.exit_code == 1
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
    assert required.exit_code == 1


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

    assert result.exit_code == 1
    assert "below the required" in result.output
