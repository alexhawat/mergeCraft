"""``mergecraft verify-behavior`` flag surface and mode entry points."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from mergecraft.cli.app import app
from tests.verify.support import CLI_FLAGS, SAMPLE_YAML_INPUT

_RUNNER = CliRunner()


def test_verify_behavior_is_registered() -> None:
    result = _RUNNER.invoke(app, ["verify-behavior", "--help"])
    assert result.exit_code == 0
    assert "verify-behavior" in result.stdout or "reproduce" in result.stdout.lower()


def test_cli_exposes_issue_61_flags_plus_absorbed_extras() -> None:
    result = _RUNNER.invoke(app, ["verify-behavior", "--help"])
    assert result.exit_code == 0
    text = result.stdout
    for flag in CLI_FLAGS:
        assert flag in text, flag


def test_cli_verify_mode_writes_a_report(tmp_path: Path) -> None:
    artifacts = tmp_path / "arts"
    criteria = tmp_path / "criteria.md"
    criteria.write_text("- Clear button removes the image\n", encoding="utf-8")
    result = _RUNNER.invoke(
        app,
        [
            "verify-behavior",
            "--mode",
            "verify",
            "--url",
            "http://127.0.0.1:8765/",
            "--criteria-file",
            str(criteria),
            "--artifacts-dir",
            str(artifacts),
            "--start-command",
            "true",
        ],
    )
    assert result.exit_code == 0 or result.exit_code == 1
    written = list(artifacts.rglob("*.json"))
    assert written


def test_cli_reproduce_mode_accepts_issue_file(tmp_path: Path) -> None:
    issue = tmp_path / "issue.md"
    issue.write_text("## Repro\n1. Open upload\n2. Click Clear\n", encoding="utf-8")
    artifacts = tmp_path / "arts"
    result = _RUNNER.invoke(
        app,
        [
            "verify-behavior",
            "--mode",
            "reproduce",
            "--url",
            "http://127.0.0.1:8765/",
            "--issue-file",
            str(issue),
            "--artifacts-dir",
            str(artifacts),
            "--base",
            "origin/main",
            "--viewport",
            "1280x720",
        ],
    )
    assert result.exit_code in {0, 1}
    assert list(artifacts.rglob("*.json"))


def test_cli_accepts_yaml_input(tmp_path: Path) -> None:
    yaml_path = tmp_path / "spec.yaml"
    yaml_path.write_text(SAMPLE_YAML_INPUT, encoding="utf-8")
    result = _RUNNER.invoke(app, ["verify-behavior", "--input", str(yaml_path)])
    assert result.exit_code in {0, 1}
    combined = f"{result.stdout}\n{result.stderr}"
    assert (
        "blocked" in combined.lower()
        or "verify" in combined.lower()
        or list(tmp_path.rglob("*.json"))
    )
