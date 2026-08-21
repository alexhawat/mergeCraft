"""Tests for ``mergecraft.context.repo_paths``."""

from __future__ import annotations

from pathlib import Path

from mergecraft.context.repo_paths import git_show_text, is_excluded_repo_path
from tests.context.support import git_commit_all, git_init_repo


def test_excluded_repo_paths_skip_common_vendor_dirs() -> None:
    assert is_excluded_repo_path(".venv/lib/python3.14/site-packages/foo.py")
    assert is_excluded_repo_path("node_modules/pkg/index.js")
    assert is_excluded_repo_path("src/demo/service.py") is False


def test_git_show_text_skips_binary_blobs_without_raising(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "readme.txt").write_text("ok\n", encoding="utf-8")
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)))
    git_init_repo(root)
    sha = git_commit_all(root)
    assert git_show_text(root, sha, "readme.txt") == "ok\n"
    assert git_show_text(root, sha, "logo.png") is None
