"""W1.2 — ``mergecraft agent`` named agents (wave plan 11, green after W3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from tests.cli.support_agent_roster import (
    bootstrap_review_repo,
    config_text,
    import_agent_roster,
    plain_cli_output,
    read_config,
    register_nous_model,
    write_config,
)
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}


def _invoke(*argv: str) -> object:
    return runner.invoke(app, list(argv), env=_DUMB_ENV)


def _require_agent_namespace() -> None:
    result = _invoke("agent", "--help")
    output = plain_cli_output(result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "create" in output
    assert "assign-model" in output


def test_agent_create_reviewer2_writes_role(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    _require_agent_namespace()
    write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = _invoke("agent", "create", "reviewer2", "--role", "reviewer")
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr
    config = read_config(tmp_path)
    entry = config.get("agents", {}).get("reviewer2", {})
    assert entry.get("role") == "reviewer"


def test_agent_create_with_after_writes_after_key(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    _require_agent_namespace()
    write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    first = _invoke("agent", "create", "reviewer2", "--role", "reviewer")
    assert first.exit_code == CLI_SUCCESS_EXIT_CODE, first.stdout + first.stderr
    second = _invoke(
        "agent",
        "create",
        "reviewer3",
        "--role",
        "reviewer",
        "--after",
        "reviewer2",
    )
    assert second.exit_code == CLI_SUCCESS_EXIT_CODE, second.stdout + second.stderr
    config = read_config(tmp_path)
    assert config["agents"]["reviewer3"]["after"] == "reviewer2"
    assert "after" not in config["agents"]["reviewer2"]


def test_after_unknown_agent_is_load_time_error(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    mod = import_agent_roster()
    raw = {
        "models": ["anthropic/claude-sonnet"],
        "agents": {
            "reviewer2": {
                "role": "reviewer",
                "after": "missing-agent",
                "modelChain": ["anthropic/claude-sonnet"],
            },
        },
    }
    with pytest.raises(Exception, match=r"unknown|after|missing-agent"):
        mod.load_roster(raw)


def test_after_cycle_is_load_time_error(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    mod = import_agent_roster()
    raw = {
        "models": ["anthropic/claude-sonnet", "openai/gpt-5.3-codex"],
        "agents": {
            "reviewer2": {
                "role": "reviewer",
                "after": "reviewer3",
                "modelChain": ["anthropic/claude-sonnet"],
            },
            "reviewer3": {
                "role": "reviewer",
                "after": "reviewer2",
                "modelChain": ["openai/gpt-5.3-codex"],
            },
        },
    }
    with pytest.raises(Exception, match=r"cycle|after"):
        mod.load_roster(raw)


@pytest.mark.parametrize(
    "bad_name",
    ["Reviewer", "-bad", "bad name", "a" * 33, "reviewer!"],
)
def test_agent_create_rejects_d11_pattern_violations(
    bad_name: str,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _require_agent_namespace()
    write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = _invoke("agent", "create", bad_name, "--role", "reviewer")
    assert result.exit_code != 0
    output = plain_cli_output(result.stdout + result.stderr).lower()
    assert "pattern" in output or "invalid" in output or "name" in output


def test_agent_create_rejects_second_orchestrator(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    _require_agent_namespace()
    write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = _invoke("agent", "create", "orchestrator2", "--role", "orchestrator")
    assert result.exit_code != 0
    output = plain_cli_output(result.stdout + result.stderr).lower()
    assert "orchestrator" in output


def test_agent_assign_model_works_on_non_agent_role_name(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _require_agent_namespace()
    bootstrap_review_repo(tmp_path, monkeypatch)
    slug = register_nous_model(tmp_path, _invoke)
    create = _invoke("agent", "create", "reviewer2", "--role", "reviewer")
    assert create.exit_code == CLI_SUCCESS_EXIT_CODE, create.stdout + create.stderr
    assign = _invoke("agent", "assign-model", "reviewer2", "p0", slug)
    assert assign.exit_code == CLI_SUCCESS_EXIT_CODE, assign.stdout + assign.stderr
    config = read_config(tmp_path)
    chain = config["agents"]["reviewer2"]["modelChain"]
    assert chain[0] == slug


def test_agent_delete_refuses_last_reviewer(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    _require_agent_namespace()
    write_config(
        tmp_path,
        """
models:
  - anthropic/claude-sonnet
agents:
  reviewer:
    modelChain:
      - anthropic/claude-sonnet
""",
    )
    monkeypatch.chdir(tmp_path)
    result = _invoke("agent", "delete", "reviewer")
    assert result.exit_code != 0
    output = plain_cli_output(result.stdout + result.stderr).lower()
    assert "reviewer" in output
    assert "last" in output or "refuse" in output or "cannot" in output
    assert "reviewer:" in config_text(tmp_path)


def test_agent_delete_refuses_last_verifier(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    _require_agent_namespace()
    write_config(
        tmp_path,
        """
models:
  - anthropic/claude-sonnet
agents:
  verifier:
    modelChain:
      - anthropic/claude-sonnet
""",
    )
    monkeypatch.chdir(tmp_path)
    result = _invoke("agent", "delete", "verifier")
    assert result.exit_code != 0
    output = plain_cli_output(result.stdout + result.stderr).lower()
    assert "verifier" in output
    yaml_text = config_text(tmp_path)
    assert yaml.safe_load(yaml_text)["agents"]["verifier"]
