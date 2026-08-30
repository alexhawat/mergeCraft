"""Tests for layered config loading (D2 / W4)."""

from __future__ import annotations

from pathlib import Path

from mergecraft.config.layered import load_layered_config_dict, merge_config_dicts


def test_merge_config_dicts_deep_merges_agents() -> None:
    merged = merge_config_dicts(
        {"agents": {"reviewer": {"modelChain": ["anthropic/claude-sonnet"]}}},
        {"agents": {"reviewer": {"modelChain": ["openai/gpt-5.3-codex"]}}},
    )
    assert merged["agents"]["reviewer"]["modelChain"] == ["openai/gpt-5.3-codex"]


def test_load_layered_config_dict_merges_local_overlay(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text(
        "agents:\n  reviewer:\n    modelChain:\n      - anthropic/claude-sonnet\n",
        encoding="utf-8",
    )
    (cfg_dir / "config.local.yaml").write_text(
        "agents:\n  reviewer:\n    modelChain:\n      - openai/gpt-5.3-codex\n",
        encoding="utf-8",
    )
    loaded = load_layered_config_dict(root=tmp_path)
    assert loaded["agents"]["reviewer"]["modelChain"] == ["openai/gpt-5.3-codex"]
