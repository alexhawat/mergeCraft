"""Tests for ``mergecraft.context.repo_paths``."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mergecraft.context import repo_paths as repo_paths_mod
from mergecraft.context.repo_paths import git_show_text, is_excluded_repo_path
from tests.context.support import git_commit_all, git_init_repo

if TYPE_CHECKING:
    import pytest


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


def test_git_show_text_does_not_buffer_oversize_blobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Byte budget is applied from the cat-file header, not after a full dump."""
    root = tmp_path / "repo"
    root.mkdir()
    blob = "x" * 8_192
    (root / "big.txt").write_text(blob, encoding="utf-8")
    (root / "ok.txt").write_text("tiny\n", encoding="utf-8")
    git_init_repo(root)
    sha = git_commit_all(root)

    payload_reads: list[int] = []
    real_popen = subprocess.Popen

    class _SpyStdout:
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def readline(self, *args: object, **kwargs: object) -> bytes:
            return self._inner.readline(*args, **kwargs)  # type: ignore[no-any-return]

        def read(self, n: int = -1) -> bytes:
            payload_reads.append(n)
            return self._inner.read(n)  # type: ignore[no-any-return]

    def _spy_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        proc = real_popen(*args, **kwargs)
        if proc.stdout is not None:
            proc.stdout = _SpyStdout(proc.stdout)  # type: ignore[assignment]
        return proc

    monkeypatch.setattr(repo_paths_mod.subprocess, "Popen", _spy_popen)

    assert git_show_text(root, sha, "ok.txt", max_bytes=16) == "tiny\n"
    payload_reads.clear()
    assert git_show_text(root, sha, "big.txt", max_bytes=16) is None
    assert payload_reads == [], "oversize blob payload must not be read into memory"
    assert git_show_text(root, sha, "big.txt", max_bytes=len(blob)) == blob
