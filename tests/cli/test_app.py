"""CLI help / version smoke tests (offline)."""

from __future__ import annotations

from typer.testing import CliRunner

from mergecraft import __version__
from mergecraft.cli.app import app

runner = CliRunner()


def test_cli_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "init" in result.stdout
    assert "auth" in result.stdout
    assert "watch" in result.stdout
    assert "diff-review" in result.stdout
    assert "gha" in result.stdout


def test_cli_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_cli_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_cli_init_help() -> None:
    result = runner.invoke(app, ["init", "--help"])
    assert result.exit_code == 0
    assert "Scaffold" in result.stdout or "scaffold" in result.stdout.lower()


def test_cli_auth_help() -> None:
    result = runner.invoke(app, ["auth", "--help"])
    assert result.exit_code == 0
    assert "codex" in result.stdout
    assert "claude" in result.stdout


def test_cli_gha_help() -> None:
    result = runner.invoke(app, ["gha", "--help"])
    assert result.exit_code == 0
