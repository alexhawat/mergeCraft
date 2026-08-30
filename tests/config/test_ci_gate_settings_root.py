"""W1.1 — settings-root resolution (wave 16, green after W2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from mergecraft.config.settings import load_repo_settings
from tests.config.support_ci_gate_settings import (
    BASE_MODEL,
    HEAD_MODEL,
    apply_env,
    init_repo_with_worktrees,
    seed_head_and_base_configs,
    write_mergecraft_config,
)

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

W2_XFAIL = pytest.mark.xfail(
    reason="green after W2: settings-root worktree resolution", strict=True
)


def test_load_repo_settings_root_reads_base_with_github_workspace_at_head(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """#573 guard — explicit ``root=`` must load the base worktree config."""
    head, base = init_repo_with_worktrees(tmp_path)
    seed_head_and_base_configs(head, base)
    apply_env(monkeypatch, github_workspace=str(head))

    settings = load_repo_settings(root=base, load_learnings_files=False)
    assert settings.model == BASE_MODEL


@W2_XFAIL
def test_cwd_worktree_wins_over_github_workspace(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """D2 — cwd in a sibling worktree must not inherit head's ``GITHUB_WORKSPACE``."""
    head, base = init_repo_with_worktrees(tmp_path)
    seed_head_and_base_configs(head, base)
    apply_env(monkeypatch, github_workspace=str(head))
    monkeypatch.chdir(base)

    settings = load_repo_settings(load_learnings_files=False)
    assert settings.model == BASE_MODEL


def test_cwd_inside_github_workspace_unchanged(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Normal CI case — cwd under ``GITHUB_WORKSPACE`` keeps today's behaviour."""
    repo = tmp_path / "workspace"
    nested = repo / "nested"
    nested.mkdir(parents=True)
    write_mergecraft_config(
        repo,
        f"model: {HEAD_MODEL}\npush: restricted\nshell: restricted\n",
    )
    apply_env(monkeypatch, github_workspace=str(repo))
    monkeypatch.chdir(nested)

    settings = load_repo_settings(load_learnings_files=False)
    assert settings.model == HEAD_MODEL


def test_mergecraft_config_wins_over_workspace_and_cwd(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """D3 — ``MERGECRAFT_CONFIG`` keeps precedence over workspace and cwd."""
    head, base = init_repo_with_worktrees(tmp_path)
    seed_head_and_base_configs(head, base)
    override = tmp_path / "override.yaml"
    override.write_text("model: custom/override\npush: restricted\nshell: restricted\n")
    apply_env(monkeypatch, github_workspace=str(head), mergecraft_config=str(override))
    monkeypatch.chdir(base)

    settings = load_repo_settings(load_learnings_files=False)
    assert settings.model == "custom/override"


def test_explicit_root_wins_over_github_workspace(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Guard — ``root=`` still beats ``GITHUB_WORKSPACE``."""
    head, base = init_repo_with_worktrees(tmp_path)
    seed_head_and_base_configs(head, base)
    apply_env(monkeypatch, github_workspace=str(head))

    settings = load_repo_settings(root=base, load_learnings_files=False)
    assert settings.model == BASE_MODEL


def test_outside_git_repo_falls_back_to_cwd(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Guard — non-repo cwd with no ``GITHUB_WORKSPACE`` resolves to cwd."""
    repo = tmp_path / "plain"
    repo.mkdir()
    write_mergecraft_config(
        repo,
        f"model: {BASE_MODEL}\npush: restricted\nshell: restricted\n",
    )
    apply_env(monkeypatch, clear_github_workspace=True)
    monkeypatch.chdir(repo)

    settings = load_repo_settings(load_learnings_files=False)
    assert settings.model == BASE_MODEL


@W2_XFAIL
def test_base_tree_validates_cleanly_when_head_config_has_unknown_key(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """End-to-end #573 shape — base load must not parse head's invalid config."""
    head, base = init_repo_with_worktrees(tmp_path)
    seed_head_and_base_configs(head, base)
    write_mergecraft_config(
        head,
        f"model: {HEAD_MODEL}\nw0TestFlag: true\npush: restricted\nshell: restricted\n",
    )
    apply_env(monkeypatch, github_workspace=str(head))
    monkeypatch.chdir(base)

    settings = load_repo_settings(load_learnings_files=False)
    assert settings.model == BASE_MODEL

    with pytest.raises(ValidationError):
        load_repo_settings(root=head, load_learnings_files=False)
