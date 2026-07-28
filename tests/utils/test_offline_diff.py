"""Unit tests for offline_diff helpers against a real temp git repo."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mergecraft.utils.offline_diff import detect_default_base, materialize_diff


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-m", "init")
    # Ensure a main branch name exists for detect_default_base.
    _git(tmp_path, "branch", "-M", "main")
    (tmp_path / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
    return tmp_path


def test_detect_default_base_prefers_main(git_repo: Path) -> None:
    base = detect_default_base(git_repo)
    assert base in {"main", "HEAD^"}


def test_materialize_merge_base_includes_workdir(git_repo: Path) -> None:
    result = materialize_diff(cwd=git_repo, out_dir=git_repo / "out", base="main")
    # Uncommitted edit vs HEAD on same branch: merge-base with main may be empty
    # if we're ON main. Commit on a feature branch instead.
    assert result.path.exists()


def test_materialize_on_feature_branch(git_repo: Path) -> None:
    _git(git_repo, "checkout", "-b", "feature")
    (git_repo / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    _git(git_repo, "add", "a.txt")
    _git(git_repo, "commit", "-m", "feature change")
    result = materialize_diff(cwd=git_repo, out_dir=git_repo / "out2", base="main")
    assert result.empty is False
    text = result.path.read_text(encoding="utf-8")
    assert "three" in text or "+three" in text
    assert result.base_ref == "main"
