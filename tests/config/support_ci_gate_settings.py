"""Shared helpers for wave 16 — CI gate settings-root contracts."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def init_repo_with_worktrees(tmp_path: Path) -> tuple[Path, Path]:
    """Create a primary repo and a sibling linked worktree.

    Returns ``(head_worktree, base_worktree)`` where *head* is the primary
    checkout and *base* is a detached sibling worktree of the same repo.
    """
    head = tmp_path / "head"
    head.mkdir()
    git(tmp_path, "init", str(head))
    git(head, "config", "user.email", "ci-gate@test.local")
    git(head, "config", "user.name", "CI Gate Test")
    (head / "README.md").write_text("ci-gate fixture\n", encoding="utf-8")
    git(head, "add", ".")
    git(head, "commit", "-m", "init")

    base = tmp_path / "base"
    git(head, "worktree", "add", str(base), "--detach")
    return head, base


def write_mergecraft_config(repo_root: Path, body: str) -> Path:
    cfg_dir = repo_root / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / "config.yaml"
    path.write_text(body.strip() + "\n", encoding="utf-8")
    return path


def commit_config(repo_root: Path, message: str) -> None:
    git(repo_root, "add", ".mergecraft/config.yaml")
    git(repo_root, "commit", "-m", message)


HEAD_MODEL = "openai/head-only-model"
BASE_MODEL = "anthropic/base-only-model"


def seed_head_and_base_configs(head: Path, base: Path) -> None:
    """Distinct model values so mis-resolution is observable."""
    write_mergecraft_config(head, f"model: {HEAD_MODEL}\npush: restricted\nshell: restricted\n")
    commit_config(head, "head config")
    write_mergecraft_config(
        base,
        f"model: {BASE_MODEL}\npush: restricted\nshell: restricted\n",
    )
    commit_config(base, "base config")


def apply_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    github_workspace: str | None = None,
    mergecraft_config: str | None = None,
    clear_github_workspace: bool = False,
) -> None:
    if clear_github_workspace:
        monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    if github_workspace is not None:
        monkeypatch.setenv("GITHUB_WORKSPACE", github_workspace)
    if mergecraft_config is not None:
        monkeypatch.setenv("MERGECRAFT_CONFIG", mergecraft_config)
    elif mergecraft_config is None and not clear_github_workspace:
        monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)


__all__ = [
    "BASE_MODEL",
    "HEAD_MODEL",
    "apply_env",
    "commit_config",
    "git",
    "init_repo_with_worktrees",
    "seed_head_and_base_configs",
    "write_mergecraft_config",
]
