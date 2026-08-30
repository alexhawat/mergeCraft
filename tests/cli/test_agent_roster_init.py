"""W1.8 — init seeds working reviewer pipeline (wave plan 11)."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest
from tests.cli.support_agent_roster import (
    agents_entry,
    init_git_repo,
    plain_cli_output,
    read_config,
    write_config,
)
from tests.cli.support_provider_registry import (
    indexed_env_key,
    stub_mergecraft_env,
)
from tests.cli.test_provider_auth_cmd import _patch_nous_validator
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE
from mergecraft.models import PROVIDERS

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}


def _invoke(*argv: str) -> object:
    return runner.invoke(app, list(argv), env=_DUMB_ENV)


def _preferred_slug(provider: str) -> str:
    entry = PROVIDERS[provider]
    for model_id, model in entry.models.items():
        if model.preferred:
            return f"{provider}/{model_id}"
    pytest.fail(f"no preferred model for provider {provider!r}")


def test_init_plus_auth_seeds_single_model_chain_entry(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    init = _invoke("init", "--force")
    assert init.exit_code == CLI_SUCCESS_EXIT_CODE, init.stdout + init.stderr
    _patch_nous_validator(monkeypatch)
    stub_mergecraft_env(monkeypatch, tmp_path)
    auth = _invoke("provider", "auth", "nous", "--api-key", "test-nous-key")
    assert auth.exit_code == CLI_SUCCESS_EXIT_CODE, auth.stdout + auth.stderr
    config = read_config(tmp_path)
    chain = agents_entry(config, "reviewer").get("modelChain")
    assert isinstance(chain, list)
    assert len(chain) == 1


def test_seeded_entry_uses_authenticated_provider_preferred_model(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert _invoke("init", "--force").exit_code == CLI_SUCCESS_EXIT_CODE
    _patch_nous_validator(monkeypatch)
    stub_mergecraft_env(monkeypatch, tmp_path)
    auth = _invoke("provider", "auth", "nous", "--api-key", "test-nous-key")
    assert auth.exit_code == CLI_SUCCESS_EXIT_CODE, auth.stdout + auth.stderr
    expected = _preferred_slug("nous")
    chain = agents_entry(read_config(tmp_path), "reviewer").get("modelChain", [])
    assert chain == [expected]


def test_init_on_existing_roster_does_not_overwrite(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
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
    subprocess.run(["git", "add", ".mergecraft"], cwd=tmp_path, check=True, capture_output=True)
    init = _invoke("init", "--force")
    assert init.exit_code == CLI_SUCCESS_EXIT_CODE, init.stdout + init.stderr
    chain = agents_entry(read_config(tmp_path), "reviewer").get("modelChain", [])
    assert chain == ["anthropic/claude-sonnet"]


def test_review_runs_after_init_and_auth_without_third_command(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert _invoke("init", "--force").exit_code == CLI_SUCCESS_EXIT_CODE
    _patch_nous_validator(monkeypatch)
    stub_mergecraft_env(monkeypatch, tmp_path)
    auth = _invoke("provider", "auth", "nous", "--api-key", "test-nous-key")
    assert auth.exit_code == CLI_SUCCESS_EXIT_CODE, auth.stdout + auth.stderr
    patch = tmp_path / "change.diff"
    patch.write_text(
        "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(indexed_env_key(1, "API_KEY"), "test-nous-key")
    review = _invoke("review", "--diff", str(patch), "--cwd", str(tmp_path), "--dry-run")
    output = plain_cli_output(review.stdout + review.stderr).lower()
    assert review.exit_code == CLI_SUCCESS_EXIT_CODE, review.stdout + review.stderr
    assert "error" not in output or "dry-run" in output
