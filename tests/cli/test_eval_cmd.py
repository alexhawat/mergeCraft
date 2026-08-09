"""CLI tests for ``mergecraft eval`` (W11.2-4).

The CLI is the I/O shell around the pure store. These tests pin:

- The ``add`` / ``list`` / ``replay`` subcommands work end-to-end.
- The CLI exits non-zero on a regression (so a CI loop latches on it).
- The CLI round-trips with the pure store (the add command writes
  files the ``list`` and ``replay`` commands can read).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.evals.store import list_cases, load_case

runner = CliRunner()


# ── help ───────────────────────────────────────────────────────────────


def test_eval_help_lists_subcommands() -> None:
    """``mergecraft eval --help`` surfaces the three subcommands."""
    result = runner.invoke(app, ["eval", "--help"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "add" in result.stdout
    assert "list" in result.stdout
    assert "replay" in result.stdout


# ── add ────────────────────────────────────────────────────────────────


def test_eval_add_writes_case_to_disk(tmp_path: Path) -> None:
    """``mergecraft eval add`` writes a case file in the bank directory."""
    result = runner.invoke(
        app,
        [
            "eval",
            "add",
            "--id",
            "synthetic-001",
            "--title",
            "missed a fabricated deletion",
            "--category",
            "missed_finding",
            "--failure-mode",
            "missed_finding",
            "--expected-finding",
            "src/mergecraft/foo.py:42-60: 'delete' on unborn file",
            "--expected-decision",
            "block",
            "--run-id",
            "synthetic",
            "--pr-number",
            "1",
            "--author",
            "synthetic",
            "--trust-tier",
            "trusted",
            "--bank",
            str(tmp_path),
            "--body",
            "# synthetic-001\n\ndescription\n",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    target = tmp_path / "synthetic-001.md"
    assert target.is_file()
    case = load_case(target)
    assert case.id == "synthetic-001"
    assert case.expected_decision == "block"
    assert case.provenance.author_login == "synthetic"
    assert case.provenance.trust_tier == "trusted"


def test_eval_add_refuses_existing_case_without_overwrite(tmp_path: Path) -> None:
    """``mergecraft eval add`` exits non-zero when the case already exists."""
    _add_synthetic(tmp_path, case_id="synthetic-001")
    result = runner.invoke(
        app,
        [
            "eval",
            "add",
            "--id",
            "synthetic-001",
            "--title",
            "another title",
            "--category",
            "missed_finding",
            "--failure-mode",
            "missed_finding",
            "--expected-finding",
            "x",
            "--expected-decision",
            "block",
            "--bank",
            str(tmp_path),
        ],
    )
    assert result.exit_code != 0


def test_eval_add_overwrite_replaces_existing(tmp_path: Path) -> None:
    """``--overwrite`` replaces the existing case."""
    _add_synthetic(tmp_path, case_id="synthetic-001")
    result = runner.invoke(
        app,
        [
            "eval",
            "add",
            "--id",
            "synthetic-001",
            "--title",
            "updated title",
            "--category",
            "missed_finding",
            "--failure-mode",
            "missed_finding",
            "--expected-finding",
            "x",
            "--expected-decision",
            "block",
            "--bank",
            str(tmp_path),
            "--overwrite",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    case = load_case(tmp_path / "synthetic-001.md")
    assert case.title == "updated title"


def test_eval_add_rejects_invalid_expected_decision(tmp_path: Path) -> None:
    """``--expected-decision`` outside the verdict vocabulary is rejected."""
    result = runner.invoke(
        app,
        [
            "eval",
            "add",
            "--id",
            "synthetic-bad",
            "--title",
            "t",
            "--category",
            "missed_finding",
            "--failure-mode",
            "missed_finding",
            "--expected-finding",
            "x",
            "--expected-decision",
            "ship-it",
            "--bank",
            str(tmp_path),
        ],
    )
    assert result.exit_code != 0


# ── list ───────────────────────────────────────────────────────────────


def test_eval_list_default_lists_every_case(tmp_path: Path) -> None:
    """``mergecraft eval list`` returns every case in the bank."""
    _add_synthetic(tmp_path, case_id="synthetic-001")
    _add_synthetic(tmp_path, case_id="synthetic-002")
    result = runner.invoke(app, ["eval", "list", "--bank", str(tmp_path)])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "synthetic-001" in result.stdout
    assert "synthetic-002" in result.stdout


def test_eval_list_json_emits_structured_payload(tmp_path: Path) -> None:
    """``--json`` serializes the case list as JSON."""
    _add_synthetic(tmp_path, case_id="synthetic-001")
    result = runner.invoke(app, ["eval", "list", "--bank", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["id"] == "synthetic-001"
    assert payload[0]["expected_decision"] == "block"
    assert payload[0]["provenance"]["trust_tier"] == "trusted"


def test_eval_list_filters_by_category(tmp_path: Path) -> None:
    """``--category`` filters by exact category."""
    _add_synthetic(tmp_path, case_id="synthetic-001", category="missed_finding")
    _add_synthetic(tmp_path, case_id="synthetic-002", category="false_positive")
    result = runner.invoke(
        app,
        [
            "eval",
            "list",
            "--bank",
            str(tmp_path),
            "--category",
            "missed_finding",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "synthetic-001" in result.stdout
    assert "synthetic-002" not in result.stdout


def test_eval_list_filters_by_id_prefix(tmp_path: Path) -> None:
    """``--id-prefix`` filters by id prefix."""
    _add_synthetic(tmp_path, case_id="synthetic-001")
    result = runner.invoke(
        app,
        [
            "eval",
            "list",
            "--bank",
            str(tmp_path),
            "--id-prefix",
            "synthetic",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "synthetic-001" in result.stdout


def test_eval_list_surfaces_message_when_empty(tmp_path: Path) -> None:
    """``mergecraft eval list`` prints a friendly message when the bank is empty."""
    result = runner.invoke(app, ["eval", "list", "--bank", str(tmp_path)])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "no cases" in result.stdout.lower()


def test_eval_list_rejects_invalid_since_timestamp(tmp_path: Path) -> None:
    """``--since`` rejects an unparseable timestamp."""
    result = runner.invoke(
        app,
        ["eval", "list", "--bank", str(tmp_path), "--since", "not-a-date"],
    )
    assert result.exit_code != 0


# ── replay ─────────────────────────────────────────────────────────────


def test_eval_replay_passes_when_verdicts_match(tmp_path: Path) -> None:
    """``mergecraft eval replay --current-decision <expected>`` exits 0."""
    _add_synthetic(tmp_path, case_id="synthetic-001")
    result = runner.invoke(
        app,
        [
            "eval",
            "replay",
            "synthetic-001",
            "--current-decision",
            "block",
            "--bank",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "passed" in result.stdout


def test_eval_replay_exits_2_on_regression(tmp_path: Path) -> None:
    """``mergecraft eval replay`` exits 2 when the verdict drifts."""
    _add_synthetic(tmp_path, case_id="synthetic-001")
    result = runner.invoke(
        app,
        [
            "eval",
            "replay",
            "synthetic-001",
            "--current-decision",
            "auto_merge",
            "--bank",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 2
    assert "regression" in result.stdout.lower()


def test_eval_replay_reports_blocked_without_current_decision(tmp_path: Path) -> None:
    """``mergecraft eval replay`` without ``--current-decision`` is ``blocked``."""
    _add_synthetic(tmp_path, case_id="synthetic-001")
    result = runner.invoke(
        app,
        ["eval", "replay", "synthetic-001", "--bank", str(tmp_path)],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "blocked" in result.stdout.lower()


def test_eval_replay_reports_missing_case(tmp_path: Path) -> None:
    """``mergecraft eval replay <missing>`` exits 1."""
    result = runner.invoke(
        app,
        ["eval", "replay", "synthetic-missing", "--bank", str(tmp_path)],
    )
    assert result.exit_code == 1


def test_eval_replay_json_emits_structured_diff(tmp_path: Path) -> None:
    """``--json`` serializes the diff as JSON."""
    _add_synthetic(tmp_path, case_id="synthetic-001")
    result = runner.invoke(
        app,
        [
            "eval",
            "replay",
            "synthetic-001",
            "--current-decision",
            "block",
            "--bank",
            str(tmp_path),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["case_id"] == "synthetic-001"
    assert payload["status"] == "passed"
    assert payload["expected_decision"] == "block"
    assert payload["current_decision"] == "block"


# ── round-trip ─────────────────────────────────────────────────────────


def test_eval_add_list_replay_round_trip(tmp_path: Path) -> None:
    """End-to-end: add → list → replay returns the recorded case."""
    add_result = runner.invoke(
        app,
        [
            "eval",
            "add",
            "--id",
            "synthetic-e2e",
            "--title",
            "end-to-end round trip",
            "--category",
            "missed_finding",
            "--failure-mode",
            "missed_finding",
            "--expected-finding",
            "src/x.py:42",
            "--expected-decision",
            "block",
            "--bank",
            str(tmp_path),
        ],
    )
    assert add_result.exit_code == 0, add_result.stdout + add_result.stderr

    list_result = runner.invoke(app, ["eval", "list", "--bank", str(tmp_path), "--json"])
    assert list_result.exit_code == 0, list_result.stdout + list_result.stderr
    payload = json.loads(list_result.stdout)
    assert any(c["id"] == "synthetic-e2e" for c in payload)

    replay_result = runner.invoke(
        app,
        [
            "eval",
            "replay",
            "synthetic-e2e",
            "--current-decision",
            "block",
            "--bank",
            str(tmp_path),
        ],
    )
    assert replay_result.exit_code == 0, replay_result.stdout + replay_result.stderr
    assert "passed" in replay_result.stdout


# ── root help ──────────────────────────────────────────────────────────


def test_root_help_includes_eval_subcommand() -> None:
    """The Typer root command advertises the eval subcommand."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "eval" in result.stdout


# ── helpers ────────────────────────────────────────────────────────────


def _add_synthetic(
    tmp_path: Path,
    *,
    case_id: str = "synthetic-001",
    category: str = "missed_finding",
) -> None:
    """Insert a synthetic case via the CLI (test setup helper)."""
    result = runner.invoke(
        app,
        [
            "eval",
            "add",
            "--id",
            case_id,
            "--title",
            f"case {case_id}",
            "--category",
            category,
            "--failure-mode",
            category,
            "--expected-finding",
            "src/foo.py:1",
            "--expected-decision",
            "block",
            "--bank",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    # Sanity-check the case landed where the helper expects.
    assert any(c.id == case_id for c in list_cases(tmp_path))


@pytest.fixture(autouse=True)
def _capture_pytest_fixture() -> None:
    """Silence the unused-import warning for ``pytest`` when no tests use it."""
    _ = pytest
