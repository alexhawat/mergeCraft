"""AP1 agents CLI suite — ``mergecraft agents list|show|set`` (PR AP1).

Wave plan: ``.ignorelocal/03-agent-pipeline-wave-plan.md`` (PR AP1).
Reconciled green after AP1.2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from typer.testing import CliRunner

from mergecraft.agents.reviewer import REVIEWER_SYSTEM_PROMPT
from mergecraft.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()

_DEFAULT_MODELS_YAML = """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
"""


def _write_config(tmp_path: Path, body: str = _DEFAULT_MODELS_YAML) -> None:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(body.strip() + "\n", encoding="utf-8")


def test_agents_list_shows_model_prompt_and_tools(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``agents list`` surfaces model chain, prompt id, and tool count per binding."""
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["agents", "list"])

    assert result.exit_code == 0, result.stdout + result.stderr
    output = result.stdout.lower()
    assert "reviewer" in output
    assert "verifier" in output
    assert "prompt" in output
    assert "anthropic/claude-sonnet" in output or "claude-sonnet" in output
    assert "tool" in output


def test_agents_show_prints_the_resolved_prompt_and_exact_tool_names(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``agents show <role>`` prints the resolved prompt body and exact MCP tool names."""
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["agents", "show", "reviewer"])

    assert result.exit_code == 0, result.stdout + result.stderr
    output = result.stdout
    assert REVIEWER_SYSTEM_PROMPT[:80] in output
    assert "checkout_pr" in output
    assert "verify_agent_findings" not in output


def test_agents_set_overrides_one_binding(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``agents set`` writes a single binding override into ``.mergecraft/config.yaml``."""
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    override_model = "google/gemini-3.1-pro-preview"

    result = runner.invoke(
        app,
        ["agents", "set", "reviewer", "--model", override_model],
    )
    assert result.exit_code == 0, result.stdout + result.stderr

    from mergecraft.agents.registry import load_registry
    from mergecraft.config.settings import load_repo_settings

    settings = load_repo_settings(root=tmp_path)
    registry = load_registry(settings=settings, repo_root=tmp_path)
    binding = registry.resolve_role("reviewer")
    assert override_model in binding.model_chain
    assert binding.model_chain[0] == override_model
