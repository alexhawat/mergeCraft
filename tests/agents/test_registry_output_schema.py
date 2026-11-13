"""Registry schema identities remain stable without dead handoff helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.config.settings import load_repo_settings

if TYPE_CHECKING:
    from pathlib import Path

_DEFAULT_MODELS_YAML = """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
  - google/gemini-3.1-pro-preview
"""


def _write_config(tmp_path: Path, body: str) -> None:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(body.strip() + "\n", encoding="utf-8")


def _load_registry(tmp_path: Path) -> object:
    from mergecraft.agents.registry import load_registry

    settings = load_repo_settings(root=tmp_path)
    return load_registry(settings=settings, repo_root=tmp_path)


def test_specialist_registry_keeps_finding_schema(tmp_path: Path) -> None:
    from mergecraft.agents.registry import AgentRole

    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    registry = _load_registry(tmp_path)
    for role in (AgentRole.reviewer, AgentRole.recall):
        assert registry.resolve_role(role).output_schema == "mergecraft.agent_finding"
