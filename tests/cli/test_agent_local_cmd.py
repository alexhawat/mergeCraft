"""W1.3 — ``mergecraft agent-local`` scope (wave plan 11, green after W4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
from tests.cli.support_agent_roster import (
    LOCAL_CONFIG_GITIGNORE_LINE,
    bootstrap_review_repo,
    config_text,
    git_check_ignores,
    init_git_repo,
    local_config_path,
    local_config_text,
    plain_cli_output,
    read_config,
    register_nous_model,
)
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}


def _invoke(*argv: str, env: dict[str, str] | None = None) -> object:
    merged = dict(_DUMB_ENV)
    if env:
        merged.update(env)
    return runner.invoke(app, list(argv), env=merged)


def test_agent_local_writes_local_file_not_committed_config(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    bootstrap_review_repo(tmp_path, monkeypatch)
    slug = register_nous_model(tmp_path, _invoke)
    committed_before = config_text(tmp_path)
    result = _invoke("agent-local", "assign-model", "reviewer", "p0", slug)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr
    assert local_config_path(tmp_path).is_file()
    assert config_text(tmp_path) == committed_before
    local = yaml.safe_load(local_config_text(tmp_path))
    assert local["agents"]["reviewer"]["modelChain"][0] == slug


def test_agent_local_config_is_gitignored(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    init_git_repo(tmp_path)
    bootstrap_review_repo(tmp_path, monkeypatch)
    slug = register_nous_model(tmp_path, _invoke)
    result = _invoke("agent-local", "assign-model", "reviewer", "p0", slug)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr
    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert LOCAL_CONFIG_GITIGNORE_LINE in gitignore
    assert git_check_ignores(tmp_path, LOCAL_CONFIG_GITIGNORE_LINE)


def test_agent_local_overrides_win_for_cli_runs(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    # Local overrides are deliberately ignored under GitHub Actions
    # (``load_layered_config_dict`` gates the merge on
    # ``not running_in_github_actions()``, which reads ``os.environ``
    # directly, so ``CliRunner(env=...)`` cannot neutralize it). Clear the
    # ambient CI variable so this test asserts the local-run behaviour it
    # names — ``test_github_actions_ignores_local_file`` covers the CI side.
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    bootstrap_review_repo(tmp_path, monkeypatch)
    slug = register_nous_model(tmp_path, _invoke)
    committed = _invoke("agent", "assign-model", "reviewer", "p0", "anthropic/claude-sonnet")
    assert committed.exit_code == CLI_SUCCESS_EXIT_CODE, committed.stdout + committed.stderr
    local = _invoke("agent-local", "assign-model", "reviewer", "p0", slug)
    assert local.exit_code == CLI_SUCCESS_EXIT_CODE, local.stdout + local.stderr
    show = _invoke("agent", "show", "reviewer")
    output = plain_cli_output(show.stdout + show.stderr)
    assert slug in output
    assert read_config(tmp_path)["agents"]["reviewer"]["modelChain"][0] == "anthropic/claude-sonnet"


def test_github_actions_ignores_local_file(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    bootstrap_review_repo(tmp_path, monkeypatch)
    slug = register_nous_model(tmp_path, _invoke)
    local = _invoke("agent-local", "assign-model", "reviewer", "p0", slug)
    assert local.exit_code == CLI_SUCCESS_EXIT_CODE, local.stdout + local.stderr
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    from mergecraft.config.settings import load_repo_settings

    settings = load_repo_settings(root=tmp_path)
    chain = settings.agents.get("reviewer")
    assert chain is None or not chain.model_chain or chain.model_chain[0] != slug
