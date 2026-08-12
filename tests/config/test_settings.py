"""Tests for local repo settings + learnings TOC parsing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.config import (
    ModeDefinition,
    default_settings,
    load_repo_settings,
    parse_learnings_headings,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_default_settings_match_upstream() -> None:
    settings = default_settings()
    assert settings.model is None
    assert settings.modes == []
    assert settings.setup_script is None
    assert not hasattr(settings, "post_checkout_script")
    assert settings.prepush_script is None
    assert settings.stop_script is None
    assert settings.push == "restricted"
    assert settings.shell == "restricted"
    assert settings.pr_approve_enabled is False
    assert settings.auto_merge_enabled is False
    assert settings.blast_radius_override == {}
    assert settings.signed_commits is False
    assert settings.mode_instructions == {}
    assert settings.static_checks == []
    assert settings.learnings is None
    assert settings.learnings_headings == []
    assert settings.env_allowlist is None
    assert settings.xrepo_brief is None
    assert settings.xrepo_learnings is None
    assert settings.xrepo_learnings_headings == []


def test_parse_learnings_headings_ranges() -> None:
    body = """# Title
intro

## Build & test
lines

### Local
local body

### CI
ci body

## Architecture
arch
"""
    headings = parse_learnings_headings(body)
    assert [(h.depth, h.title, h.start_line, h.end_line) for h in headings] == [
        (1, "Title", 1, 14),
        (2, "Build & test", 4, 12),
        (3, "Local", 7, 9),
        (3, "CI", 10, 12),
        (2, "Architecture", 13, 14),
    ]


def test_parse_learnings_headings_empty() -> None:
    assert parse_learnings_headings(None) == []
    assert parse_learnings_headings("") == []
    assert parse_learnings_headings("no headings here\n") == []


def test_load_repo_settings_from_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text(
        """
model: anthropic/claude-sonnet
push: enabled
shell: disabled
setupScript: |
  npm ci
modes:
  - id: triage
    name: Triage
    description: Label issues
    prompt: Label the issue
modeInstructions:
  triage: be concise
envAllowlist: |
  MY_CUSTOM_VAR
""",
        encoding="utf-8",
    )
    (cfg_dir / "learnings.md").write_text(
        "## Build\nrun make test\n\n## Notes\nok\n",
        encoding="utf-8",
    )

    settings = load_repo_settings(root=tmp_path)
    assert settings.model == "anthropic/claude-sonnet"
    assert settings.push == "enabled"
    assert settings.shell == "disabled"
    assert settings.setup_script is not None
    assert "npm ci" in settings.setup_script
    assert len(settings.modes) == 1
    assert isinstance(settings.modes[0], ModeDefinition)
    assert settings.modes[0].id == "triage"
    assert settings.mode_instructions["triage"] == "be concise"
    assert settings.env_allowlist is not None
    assert "MY_CUSTOM_VAR" in settings.env_allowlist
    assert settings.learnings is not None
    assert "## Build" in settings.learnings
    assert [h.title for h in settings.learnings_headings] == ["Build", "Notes"]


def test_load_repo_settings_mergecraft_config_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "custom.yaml"
    cfg.write_text("model: openai/gpt\npush: disabled\n", encoding="utf-8")
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(cfg))
    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)
    assert settings.model == "openai/gpt"
    assert settings.push == "disabled"


def test_load_repo_settings_missing_returns_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    settings = load_repo_settings(root=tmp_path)
    assert settings.model_dump() == default_settings().model_dump()


def test_snake_and_camel_aliases(tmp_path: Path) -> None:
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        "setup_script: echo hi\npr_approve_enabled: true\nautoMergeEnabled: true\n",
        encoding="utf-8",
    )
    settings = load_repo_settings(cfg, root=tmp_path, load_learnings_files=False)
    assert settings.setup_script == "echo hi"
    assert settings.pr_approve_enabled is True
    assert settings.auto_merge_enabled is True


def test_blast_radius_override_parses_per_category(tmp_path: Path) -> None:
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        "blastRadiusOverride:\n  source_without_tests:\n    lane: high\n",
        encoding="utf-8",
    )
    settings = load_repo_settings(cfg, root=tmp_path, load_learnings_files=False)
    assert settings.blast_radius_override == {"source_without_tests": {"lane": "high"}}
    assert settings.auto_merge_enabled is False


def test_analyzers_block_parses_and_merges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text(
        """
analyzers:
  enabled: true
  inlineBudget: 8
  baseComparison: offline
  overrides:
    actionlint:
      enabled: true
""",
        encoding="utf-8",
    )
    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)
    assert settings.analyzers.enabled is True
    assert settings.analyzers.inline_budget == 8
    assert settings.analyzers.overrides["actionlint"].enabled is True


def test_unknown_analyzer_id_emits_warning_not_silent_drop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from loguru import logger

    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text(
        """
analyzers:
  overrides:
    not-a-real-analyzer:
      enabled: true
""",
        encoding="utf-8",
    )
    messages: list[str] = []
    sink_id = logger.add(lambda record: messages.append(record.record["message"]), level="WARNING")
    try:
        load_repo_settings(root=tmp_path, load_learnings_files=False)
    finally:
        logger.remove(sink_id)
    assert any("not-a-real-analyzer" in message for message in messages)
