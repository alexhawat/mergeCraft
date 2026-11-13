"""Roster writes work on the commented config that ``mergecraft init`` generates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.cli.support_agent_roster import agents_entry, init_git_repo, read_config
from tests.cli.support_provider_registry import stub_mergecraft_env
from tests.cli.test_provider_auth_cmd import _patch_api_key_validator
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE
from mergecraft.config.io import config_has_yaml_comments

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}
_UNREGISTERED = "opencode-go/deepseek-v4.1-flash"


def _invoke(*argv: str) -> object:
    return runner.invoke(app, list(argv), env=_DUMB_ENV)


def _quickstart_repo(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Run the Quickstart steps that precede ``agent assign-model``."""
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    init = _invoke("init", "--force")
    assert init.exit_code == CLI_SUCCESS_EXIT_CODE, init.stdout + init.stderr
    _patch_api_key_validator(monkeypatch)
    stub_mergecraft_env(monkeypatch, tmp_path)
    auth = _invoke("provider", "auth", "opencode-go", "--api-key", "test-opencode-go-key")
    assert auth.exit_code == CLI_SUCCESS_EXIT_CODE, auth.stdout + auth.stderr
    config_path = tmp_path / ".mergecraft" / "config.yaml"
    # The premise of these tests: init writes a config that carries comments.
    assert config_has_yaml_comments(config_path)
    return config_path


def _comment_lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if "#" in line]


def test_assign_unregistered_model_after_init_registers_it_and_keeps_comments(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    config_path = _quickstart_repo(tmp_path, monkeypatch)
    comments_before = _comment_lines(config_path)

    result = _invoke("agent", "assign-model", "reviewer", "p0", _UNREGISTERED)

    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr
    config = read_config(tmp_path)
    assert agents_entry(config, "reviewer")["modelChain"][0] == _UNREGISTERED
    provider = next(row for row in config["providers"] if row["label"] == "opencode-go")
    assert "deepseek-v4.1-flash" in [row["id"] for row in provider["models"]]
    assert _comment_lines(config_path) == comments_before


def test_assign_registered_model_after_init_keeps_comments(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    config_path = _quickstart_repo(tmp_path, monkeypatch)
    comments_before = _comment_lines(config_path)
    seeded = agents_entry(read_config(tmp_path), "reviewer")["modelChain"][0]

    result = _invoke("agent", "assign-model", "verifier", "p0", seeded)

    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr
    assert agents_entry(read_config(tmp_path), "verifier")["modelChain"][0] == seeded
    assert _comment_lines(config_path) == comments_before


def test_remove_model_after_init_keeps_comments(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    config_path = _quickstart_repo(tmp_path, monkeypatch)
    comments_before = _comment_lines(config_path)
    assert (
        _invoke("agent", "assign-model", "reviewer", "p1", _UNREGISTERED).exit_code
        == CLI_SUCCESS_EXIT_CODE
    )

    result = _invoke("agent", "remove-model", "reviewer", "p1")

    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr
    assert _UNREGISTERED not in agents_entry(read_config(tmp_path), "reviewer")["modelChain"]
    assert _comment_lines(config_path) == comments_before
