"""RED tests for ordered ``models:`` config parsing (issue #14 / W16, D13)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.config import load_repo_settings
from mergecraft.config.settings import RepoSettings

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


_ORDERED_MODELS = (
    "anthropic/claude-sonnet",
    "openai/gpt-5.3-codex",
    "google/gemini-3.1-pro-preview",
)


@pytest.mark.xfail(
    reason="green after W17: models list parses into RepoSettings (#14)", strict=False
)
def test_load_repo_settings_parses_models_ordered_list(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text(
        """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
  - google/gemini-3.1-pro-preview
""",
        encoding="utf-8",
    )

    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)

    assert "models" in RepoSettings.model_fields
    assert settings.models == list(_ORDERED_MODELS)


@pytest.mark.xfail(reason="green after W17: scalar model back-compat unchanged (#14)", strict=False)
def test_load_repo_settings_scalar_model_unchanged_without_models_list(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text(
        "model: anthropic/claude-sonnet\n",
        encoding="utf-8",
    )

    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)

    assert settings.model == "anthropic/claude-sonnet"
    assert "models" in RepoSettings.model_fields
    assert settings.models is None
