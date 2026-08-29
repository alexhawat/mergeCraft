"""Shared helpers for wave plan 11 — agent roster, model priority & multi-reviewer."""

from __future__ import annotations

import importlib
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.cli.support_provider_registry import (
    NOUS_BASE_URL,
    NOUS_TENCENT_HY3,
    format_model_slug,
    read_config,
    scaffold_mergecraft_home,
    scaffold_workflow_file,
    stub_mergecraft_env,
    write_agents_model_chain,
)

AGENT_ROSTER_MODULE = "mergecraft.config.agent_roster"
AGENT_CMD_MODULE = "mergecraft.cli.agent_cmd"
AGENT_LOCAL_CMD_MODULE = "mergecraft.cli.agent_local_cmd"
REVIEWER_MERGE_MODULE = "mergecraft.agents.reviewer_merge"
AUTH_MANIFEST_MODULE = "mergecraft.cli.workflow_cmd"

LOCAL_CONFIG_REL = ".mergecraft/config.local.yaml"
LOCAL_CONFIG_GITIGNORE_LINE = LOCAL_CONFIG_REL

DEFAULT_MODELS_YAML = """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
"""

MALFORMED_SLOTS: tuple[str, ...] = ("p-1", "pX", "1", "p 0")

W2_XFAIL = pytest.mark.xfail(reason="green after W2: slot primitives", strict=False)
W4_XFAIL = pytest.mark.xfail(reason="green after W4: agent-local scope", strict=False)
W5_XFAIL = pytest.mark.xfail(reason="green after W5: registry multiplicity", strict=False)
W7_XFAIL = pytest.mark.xfail(reason="green after W7: auth manifest fail-closed", strict=False)

WORKFLOW_INDEXED_STEP = """\
name: mergecraft
on:
  pull_request_target:
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft PR review (indexed)
        uses: alexhawat/mergeCraft@pre-0.0.1
        with:
          model: nous/tencent/hy3
        env:
          LLM_PROVIDER_1: nous
          LLM_PROVIDER_1_API_KEY: ${{ secrets.NOUS_API_KEY }}
"""

WORKFLOW_GATED_STEP = """\
name: mergecraft
on:
  pull_request_target:
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft PR review (gated)
        if: ${{ secrets.OPENAI_API_KEY != '' }}
        uses: alexhawat/mergeCraft@pre-0.0.1
        with:
          model: openai/gpt-codex
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
"""


def import_module_or_fail(module: str) -> Any:
    """Import *module* or fail with a clear message (collection-safe)."""
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        pytest.fail(f"{module} is not implemented yet: {exc}")


def import_agent_roster() -> Any:
    return import_module_or_fail(AGENT_ROSTER_MODULE)


def import_agent_cmd() -> Any:
    return import_module_or_fail(AGENT_CMD_MODULE)


def import_agent_local_cmd() -> Any:
    return import_module_or_fail(AGENT_LOCAL_CMD_MODULE)


def import_reviewer_merge() -> Any:
    return import_module_or_fail(REVIEWER_MERGE_MODULE)


def require_parse_auth_manifest() -> Any:
    module = import_module_or_fail(AUTH_MANIFEST_MODULE)
    if not hasattr(module, "parse_auth_manifest"):
        pytest.fail(f"{AUTH_MANIFEST_MODULE}.parse_auth_manifest is not implemented")
    return module.parse_auth_manifest


def require_roster_auth_validation() -> Any:
    for module_name in (
        "mergecraft.config.agent_roster",
        "mergecraft.review.roster_auth",
        AUTH_MANIFEST_MODULE,
    ):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        for attr in ("validate_roster_against_auth_manifest", "validate_roster_at_run_start"):
            fn = getattr(module, attr, None)
            if callable(fn):
                return fn
    pytest.fail("roster auth manifest run-start validator is not implemented")


def write_config(tmp_path: Path, body: str = DEFAULT_MODELS_YAML) -> Path:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / "config.yaml"
    path.write_text(body.strip() + "\n", encoding="utf-8")
    return path


def config_text(tmp_path: Path) -> str:
    path = tmp_path / ".mergecraft" / "config.yaml"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def local_config_text(tmp_path: Path) -> str:
    path = tmp_path / LOCAL_CONFIG_REL
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def local_config_path(tmp_path: Path) -> Path:
    return tmp_path / LOCAL_CONFIG_REL


def agents_entry(config: dict[str, Any], name: str) -> dict[str, Any]:
    agents = config.get("agents")
    if not isinstance(agents, dict):
        return {}
    entry = agents.get(name)
    return entry if isinstance(entry, dict) else {}


def init_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    for args in (
        ["git", "config", "user.email", "agent-roster@test.local"],
        ["git", "config", "user.name", "Agent Roster Test"],
    ):
        subprocess.run(args, cwd=tmp_path, check=True, capture_output=True)
    readme = tmp_path / "README.md"
    readme.write_text("agent roster fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )


def git_check_ignores(repo_root: Path, rel_path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", rel_path],
        cwd=repo_root,
        capture_output=True,
    )
    return result.returncode == 0


def bootstrap_review_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    workflow_body: str = WORKFLOW_INDEXED_STEP,
) -> None:
    """Minimal repo with config, workflow, and provider registry for roster CLI tests."""
    scaffold_mergecraft_home(tmp_path, config_body=DEFAULT_MODELS_YAML.strip())
    monkeypatch.chdir(tmp_path)
    stub_mergecraft_env(monkeypatch, tmp_path)
    scaffold_workflow_file(tmp_path, workflow_body)


def register_nous_model(tmp_path: Path, invoke: Any) -> str:
    add_provider = invoke(
        "provider",
        "add",
        "--label",
        "nous",
        "--url",
        NOUS_BASE_URL,
        "--harness",
        "opencode",
    )
    assert add_provider.exit_code == 0, add_provider.stdout + add_provider.stderr
    add_model = invoke("model", "add", "--provider", "nous", NOUS_TENCENT_HY3)
    assert add_model.exit_code == 0, add_model.stdout + add_model.stderr
    return format_model_slug("nous", NOUS_TENCENT_HY3)


def plain_cli_output(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def two_reviewer_config(extra: str = "") -> str:
    return (
        DEFAULT_MODELS_YAML
        + """
agents:
  reviewer:
    modelChain:
      - anthropic/claude-sonnet
  reviewer2:
    role: reviewer
    modelChain:
      - openai/gpt-5.3-codex
"""
        + extra
    )


__all__ = [
    "AGENT_CMD_MODULE",
    "AGENT_LOCAL_CMD_MODULE",
    "AGENT_ROSTER_MODULE",
    "AUTH_MANIFEST_MODULE",
    "DEFAULT_MODELS_YAML",
    "LOCAL_CONFIG_GITIGNORE_LINE",
    "LOCAL_CONFIG_REL",
    "MALFORMED_SLOTS",
    "REVIEWER_MERGE_MODULE",
    "W2_XFAIL",
    "W4_XFAIL",
    "W5_XFAIL",
    "W7_XFAIL",
    "WORKFLOW_GATED_STEP",
    "WORKFLOW_INDEXED_STEP",
    "agents_entry",
    "bootstrap_review_repo",
    "config_text",
    "format_model_slug",
    "git_check_ignores",
    "import_agent_cmd",
    "import_agent_local_cmd",
    "import_agent_roster",
    "import_reviewer_merge",
    "init_git_repo",
    "local_config_path",
    "local_config_text",
    "plain_cli_output",
    "read_config",
    "register_nous_model",
    "require_parse_auth_manifest",
    "require_roster_auth_validation",
    "scaffold_mergecraft_home",
    "scaffold_workflow_file",
    "stub_mergecraft_env",
    "two_reviewer_config",
    "write_agents_model_chain",
    "write_config",
]
