"""Real repository boundaries for the optional result-cache source identity."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from mergecraft.utils.review_source_context import review_source_context_digest

if TYPE_CHECKING:
    import pytest


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_context_tracks_files_commits_and_moving_base(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    source = tmp_path / "dependency.py"
    source.write_text("result = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "first")
    _git(tmp_path, "branch", "base")
    first = review_source_context_digest(cwd=tmp_path, base_ref="base")
    assert first is not None
    assert first == review_source_context_digest(cwd=tmp_path, base_ref="base")
    source.write_text("result = 2\n")
    dirty = review_source_context_digest(cwd=tmp_path, base_ref="base")
    assert dirty is not None
    assert dirty != first
    _git(tmp_path, "commit", "-am", "second", "-q")
    committed = review_source_context_digest(cwd=tmp_path, base_ref="base")
    assert committed is not None
    assert committed != dirty
    _git(tmp_path, "branch", "-f", "base", "HEAD")
    moved = review_source_context_digest(cwd=tmp_path, base_ref="base")
    assert moved is not None
    assert moved != committed
    (tmp_path / "new_context.py").write_text("other = True\n")
    assert review_source_context_digest(cwd=tmp_path, base_ref="base") != moved


def test_unidentifiable_context_declines_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert review_source_context_digest(cwd=tmp_path, base_ref=None) is None
    _git(tmp_path, "init", "-q")
    assert review_source_context_digest(cwd=tmp_path, base_ref="HEAD") is not None
    (tmp_path / "large.py").write_text("value = 1\n")
    monkeypatch.setattr("mergecraft.utils.review_source_context._MAX_BYTES", 1)
    assert review_source_context_digest(cwd=tmp_path, base_ref="HEAD") is None


def test_source_fingerprint_never_follows_external_symlinks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    external = tmp_path / "external"
    external.write_text("not review source")
    (repo / "link").symlink_to(external)
    assert review_source_context_digest(cwd=repo, base_ref=None) is None
