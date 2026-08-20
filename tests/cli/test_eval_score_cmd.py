"""`mergecraft eval score` output stays byte-compatible under B1 (D3 regression guard).

B1 extends ``ScoreReport`` with a large new metric surface (`f1`,
`corpus_confirmed_precision`, `strict_precision`, the FP ledger, `by_category`
/ `by_severity`, ...). ``cli/eval_cmd.py::score`` builds its ``--json`` output
from a hand-picked dict of eight named keys rather than
``report.model_dump()``, and the human-readable path goes through
``format_report()`` unchanged — so new fields on the model must not change
what this command emits today.

These tests exercise only the *existing*, unmodified code path, so they
already pass before B1.2 lands and must keep passing unchanged afterwards.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """Strip Rich's ANSI styling so line-content assertions survive highlighting."""
    return _ANSI_RE.sub("", text)


_EXPECTED_ISSUES = [
    {"id": "x-1", "path": "src/app.py", "start_line": 10, "end_line": 12, "severity": "high"}
]
_ACTUAL_FINDINGS = [
    {
        "path": "src/app.py",
        "start_line": 11,
        "end_line": 11,
        "severity": "Major",
        "message": "totally different wording",
    }
]


def _write_json(tmp_path: Path, name: str, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(rows))
    return path


def test_eval_score_json_output_keeps_its_existing_key_set(tmp_path: Path) -> None:
    actual = _write_json(tmp_path, "actual.json", _ACTUAL_FINDINGS)
    expected = _write_json(tmp_path, "expected.json", _EXPECTED_ISSUES)

    result = runner.invoke(app, ["eval", "score", str(actual), str(expected), "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert set(payload) == {
        "schema_version",
        "total_issues",
        "total_reported",
        "found",
        "recall",
        "precision",
        "severity_agreement",
        "missed_issue_ids",
        "matches",
    }


def test_eval_score_json_output_values_are_unchanged(tmp_path: Path) -> None:
    actual = _write_json(tmp_path, "actual.json", _ACTUAL_FINDINGS)
    expected = _write_json(tmp_path, "expected.json", _EXPECTED_ISSUES)

    result = runner.invoke(app, ["eval", "score", str(actual), str(expected), "--json"])

    payload = json.loads(result.stdout)
    assert payload["total_issues"] == 1
    assert payload["total_reported"] == 1
    assert payload["found"] == 1
    assert payload["recall"] == 1.0
    assert payload["precision"] == 1.0
    assert payload["missed_issue_ids"] == []
    assert payload["matches"][0]["issue_id"] == "x-1"


def test_eval_score_human_output_keeps_its_existing_lines(tmp_path: Path) -> None:
    actual = _write_json(tmp_path, "actual.json", _ACTUAL_FINDINGS)
    expected = _write_json(tmp_path, "expected.json", _EXPECTED_ISSUES)

    result = runner.invoke(app, ["eval", "score", str(actual), str(expected)])
    output = _plain(result.stdout + result.stderr)

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "baseline issues : 1" in output
    assert "findings reported: 1" in output
    assert "located          : 1" in output
    assert "recall           : 100.00%" in output
    assert "corpus-confirmed : 100.00%" in output


def test_eval_score_min_recall_gate_is_unchanged(tmp_path: Path) -> None:
    actual = _write_json(tmp_path, "actual.json", [])
    expected = _write_json(tmp_path, "expected.json", _EXPECTED_ISSUES)

    result = runner.invoke(
        app, ["eval", "score", str(actual), str(expected), "--min-recall", "0.5"]
    )
    output = _plain(result.stdout + result.stderr)

    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "recall 0.00% is below the required 50.00%" in output
