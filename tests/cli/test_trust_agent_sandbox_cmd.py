"""W1.1b — trust agentSandbox CLI surface (wave plan 15, green after W2)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import yaml
from tests.trust_credentials.support import load_config_dict, write_trust_config
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_CONFIRM_FLAG = "--i-understand-same-repo-sandbox"


def _init_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "trust@test.local"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Trust Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    readme = tmp_path / "README.md"
    readme.write_text("trust cli\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )


def test_trust_show_prints_configured_and_resolved_agent_sandbox(tmp_path: Path) -> None:
    """trust show prints tier, resolved_from, and the resolved answer for this run."""
    write_trust_config(tmp_path, agent_sandbox="dispatch", self_review="analyzers")
    result = runner.invoke(app, ["trust", "show", "--cwd", str(tmp_path)])
    assert result.exit_code == 0, result.output
    out = result.output.lower()
    assert "agentsandbox" in out or "agent sandbox" in out
    assert "dispatch" in out
    assert "resolved" in out or "resolved from" in out


def test_set_agent_sandbox_writes_key(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """set-agent-sandbox writes trust.agentSandbox offline."""
    write_trust_config(tmp_path, agent_sandbox="never")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["trust", "set-agent-sandbox", "dispatch", "--cwd", str(tmp_path)])
    assert result.exit_code == 0, result.output
    config = load_config_dict(tmp_path / ".mergecraft" / "config.yaml")
    assert config.get("trust", {}).get("agentSandbox") == "dispatch"


def test_set_agent_sandbox_same_repo_requires_confirmation(tmp_path: Path) -> None:
    """Loosening to same-repo requires a confirmation flag; tightening does not."""
    write_trust_config(tmp_path, agent_sandbox="dispatch")
    blocked = runner.invoke(
        app, ["trust", "set-agent-sandbox", "same-repo", "--cwd", str(tmp_path)]
    )
    assert blocked.exit_code != 0
    assert "same-repo" in blocked.output.lower() or "confirm" in blocked.output.lower()

    allowed = runner.invoke(
        app,
        [
            "trust",
            "set-agent-sandbox",
            "same-repo",
            _CONFIRM_FLAG,
            "--cwd",
            str(tmp_path),
        ],
    )
    assert allowed.exit_code == 0, allowed.output
    config = load_config_dict(tmp_path / ".mergecraft" / "config.yaml")
    assert config.get("trust", {}).get("agentSandbox") == "same-repo"

    tighten = runner.invoke(app, ["trust", "set-agent-sandbox", "never", "--cwd", str(tmp_path)])
    assert tighten.exit_code == 0, tighten.output


def test_set_agent_sandbox_is_offline_no_workflow_edit(tmp_path: Path) -> None:
    """set-agent-sandbox touches only config — no workflow or API edits."""
    workflow = tmp_path / ".github" / "workflows" / "mergecraft.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: mergecraft\n", encoding="utf-8")
    before = workflow.read_text(encoding="utf-8")
    write_trust_config(tmp_path, agent_sandbox="never")
    result = runner.invoke(app, ["trust", "set-agent-sandbox", "dispatch", "--cwd", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert workflow.read_text(encoding="utf-8") == before


def test_init_scaffolds_agent_sandbox_default_with_tier_comment(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """init writes agentSandbox at dispatch with inline tier documentation."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    with patch("mergecraft.cli.init_cmd.seed_builtin_providers"):
        result = runner.invoke(app, ["init", "--force"])
    assert result.exit_code == 0, result.output
    config_path = tmp_path / ".mergecraft" / "config.yaml"
    raw = config_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    assert data.get("trust", {}).get("agentSandbox") == "dispatch"
    assert re.search(r"never|merged-only|dispatch|same-repo", raw, re.IGNORECASE)
    assert "fork" in raw.lower()


def _write_commented_config(tmp_path: Path) -> Path:
    config_dir = tmp_path / ".mergecraft"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    config_path.write_text(
        "# tier docs — do not strip\n"
        "trust:\n"
        "  selfReview: 'off'\n"
        "  agentSandbox: 'dispatch'\n"
        "model: anthropic/claude-sonnet\n"
        "push: restricted\n"
        "shell: restricted\n",
        encoding="utf-8",
    )
    return config_path


def test_set_agent_sandbox_refuses_commented_config_and_leaves_file_intact(
    tmp_path: Path,
) -> None:
    """W2 option (b) — setter refuses rather than destroying scaffold comments."""
    config_path = _write_commented_config(tmp_path)
    before = config_path.read_text(encoding="utf-8")
    result = runner.invoke(app, ["trust", "set-agent-sandbox", "never", "--cwd", str(tmp_path)])
    assert result.exit_code != 0, result.output
    assert "comment" in result.output.lower() or "refusing" in result.output.lower()
    assert config_path.read_text(encoding="utf-8") == before


def test_set_self_review_refuses_commented_config_and_leaves_file_intact(
    tmp_path: Path,
) -> None:
    """set-self-review shares the commented-config refusal path."""
    config_path = _write_commented_config(tmp_path)
    before = config_path.read_text(encoding="utf-8")
    result = runner.invoke(app, ["trust", "set-self-review", "analyzers", "--cwd", str(tmp_path)])
    assert result.exit_code != 0, result.output
    assert "comment" in result.output.lower() or "refusing" in result.output.lower()
    assert config_path.read_text(encoding="utf-8") == before
