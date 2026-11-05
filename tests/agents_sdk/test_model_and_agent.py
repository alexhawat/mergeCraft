"""Model resolution and review_agent tool wiring (no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("agents")

from mergecraft.agents_sdk.agent import review_agent
from mergecraft.agents_sdk.model import AgentsSdkModelConfig, resolve_model_config


def test_resolve_model_config_openai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    cfg = resolve_model_config()
    assert cfg.api_key == "test-key"
    assert cfg.openai_model_name() == "gpt-4o-mini"


def test_resolve_model_config_opencode_go_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "go-key")
    cfg = resolve_model_config()
    assert cfg.api_key == "go-key"
    assert cfg.base_url == "https://opencode.ai/zen/v1"
    assert cfg.model.endswith("deepseek-v4.1-flash")


def test_review_agent_exposes_mergecraft_tools(tmp_path: Path) -> None:
    config = AgentsSdkModelConfig(
        model="gpt-4o-mini",
        base_url=None,
        api_key_env="OPENAI_API_KEY",
        api_key="dummy",
    )
    agent = review_agent(
        repo_root=tmp_path,
        model_config=config,
        allowed_paths=frozenset({"src/demo.py"}),
    )
    tool_names = {getattr(tool, "name", None) or tool.__name__ for tool in agent.tools}
    assert "review_change" in tool_names
    assert "get_policy" in tool_names
