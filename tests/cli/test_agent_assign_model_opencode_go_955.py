"""Issue #955 — one-shot assign-model for harness providers without custom base URLs."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import yaml
from tests.cli.support_agent_roster import (
    scaffold_workflow_file,
    stub_mergecraft_env,
)
from tests.cli.support_provider_registry import scaffold_mergecraft_home
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}
_PLAIN = re.compile(r"\x1b\[[0-9;]*m")


def _invoke(*argv: str) -> object:
    return runner.invoke(app, list(argv), env=_DUMB_ENV)


_WORKFLOW_API_KEY_ONLY = """\
name: mergecraft
on:
  pull_request_target:
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft PR review
        uses: alexhawat/mergeCraft@pre-0.0.1
        with:
          model: opencode-go/glm-5.1
        env:
          LLM_PROVIDER_1_API_KEY: ${{ secrets.LLM_PROVIDER_1_API_KEY }}
"""

_OPENCODE_GO_CONFIG = """
models:
  - opencode-go/glm-5.1
providers:
  - label: opencode-go
    harness: opencode
    envIndex: 1
    authKind: api_key
agents:
  reviewer:
    role: reviewer
    modelChain:
      - opencode-go/glm-5.1
"""

_OPENCODE_GO_CONFIG_NULL_URL = """
models:
  - opencode-go/glm-5.1
providers:
  - label: opencode-go
    harness: opencode
    envIndex: 1
    authKind: api_key
    url: null
agents:
  reviewer:
    role: reviewer
    modelChain:
      - opencode-go/glm-5.1
"""


def _bootstrap_opencode_go_repo(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    scaffold_mergecraft_home(tmp_path, config_body=_OPENCODE_GO_CONFIG.strip())
    monkeypatch.chdir(tmp_path)
    stub_mergecraft_env(monkeypatch, tmp_path)
    scaffold_workflow_file(tmp_path, _WORKFLOW_API_KEY_ONLY)


def test_assign_model_opencode_go_registers_wires_roster_and_workflow_model(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """One ``assign-model`` replaces model add + assign + workflow model add --apply."""
    _bootstrap_opencode_go_repo(tmp_path, monkeypatch)
    slug = "opencode-go/deepseek-v4.1-flash"
    result = _invoke("agent", "assign-model", "reviewer", "p0", slug)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr

    config = yaml.safe_load((tmp_path / ".mergecraft" / "config.yaml").read_text())
    reviewer = config["agents"]["reviewer"]
    assert reviewer["modelChain"][0] == slug
    provider_row = config["providers"][0]
    model_ids = [row["id"] for row in provider_row.get("models", []) if isinstance(row, dict)]
    assert "deepseek-v4.1-flash" in model_ids

    workflow_text = (tmp_path / ".github/workflows/mergecraft.yml").read_text()
    assert "LLM_PROVIDER_1: opencode-go" in workflow_text
    assert "LLM_PROVIDER_1_API_KEY:" not in workflow_text
    assert "OPENCODE_GO_API_KEY" in workflow_text
    assert slug in workflow_text
    assert "with:" in workflow_text


def test_assign_model_opencode_go_with_explicit_null_url_registry(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """YAML ``url: null`` must not stringify to a truthy custom-provider URL."""
    scaffold_mergecraft_home(tmp_path, config_body=_OPENCODE_GO_CONFIG_NULL_URL.strip())
    monkeypatch.chdir(tmp_path)
    stub_mergecraft_env(monkeypatch, tmp_path)
    scaffold_workflow_file(tmp_path, _WORKFLOW_API_KEY_ONLY)

    slug = "opencode-go/deepseek-v4.1-flash"
    result = _invoke("agent", "assign-model", "reviewer", "p0", slug)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr

    workflow_text = (tmp_path / ".github/workflows/mergecraft.yml").read_text()
    assert "LLM_PROVIDER_1: opencode-go" in workflow_text
    assert "OPENCODE_GO_API_KEY" in workflow_text
    assert "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_1" not in workflow_text
    assert "None" not in workflow_text


def test_workflow_provider_add_opencode_go_without_url(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _bootstrap_opencode_go_repo(tmp_path, monkeypatch)
    before = (tmp_path / ".github/workflows/mergecraft.yml").read_text()
    result = _invoke("workflow", "provider", "add", "--label", "opencode-go", "--apply")
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr
    after = (tmp_path / ".github/workflows/mergecraft.yml").read_text()
    assert after != before
    assert "LLM_PROVIDER_1: opencode-go" in after
    assert "LLM_PROVIDER_1_API_KEY:" not in after
    assert "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_1" not in after
