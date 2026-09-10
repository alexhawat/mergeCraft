"""Default local review includes eligible untracked additions (RA1.5, N7/D11).

A repository with a committed ``existing.py`` and an untracked ``new_bug.py``
produced ``empty=True`` under default materialization, and the offline review
mapped that to a passed review. These tests use real Git in disposable repos —
a mocked runner returning a canned diff cannot see what ``git diff`` omits.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from mergecraft.utils.offline_diff import (
    git_range_diff,
    git_staged_diff,
    materialize_diff,
)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _init_repo(tmp_path: Path, *, gitignore: str | None = None) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "existing.py").write_text("def existing():\n    return 1\n", encoding="utf-8")
    if gitignore is not None:
        (repo / ".gitignore").write_text(gitignore, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    _git(repo, "checkout", "-b", "feature")
    return repo


def _limitations(result: Any) -> Any:
    return getattr(result, "coverage_limitations", None)


def _reports(limitations: Any, needle: str) -> bool:
    return any(needle in str(item) for item in (limitations or ()))


def test_default_materialization_includes_an_untracked_addition(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "new_bug.py").write_text("def bug():\n    return 1 / 0\n", encoding="utf-8")

    result = materialize_diff(cwd=repo, out_dir=tmp_path / "out", base="main")

    text = result.path.read_text(encoding="utf-8")
    assert "new_bug.py" in text
    assert result.empty is False


def test_mixed_tracked_and_untracked_changes_include_both(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "existing.py").write_text("def existing():\n    return 2\n", encoding="utf-8")
    _git(repo, "add", "existing.py")
    _git(repo, "commit", "-m", "tracked change")
    (repo / "new_bug.py").write_text("def bug():\n    return 1 / 0\n", encoding="utf-8")

    result = materialize_diff(cwd=repo, out_dir=tmp_path / "out", base="main")

    text = result.path.read_text(encoding="utf-8")
    assert "existing.py" in text
    assert "new_bug.py" in text


def test_staged_mode_semantics_are_unchanged(tmp_path: Path) -> None:
    """Guard — staged mode has a defined meaning and untracked files are not in it."""
    repo = _init_repo(tmp_path)
    (repo / "existing.py").write_text("def existing():\n    return 3\n", encoding="utf-8")
    _git(repo, "add", "existing.py")
    (repo / "new_bug.py").write_text("def bug():\n    return 1 / 0\n", encoding="utf-8")

    text = git_staged_diff(cwd=repo)

    assert "existing.py" in text
    assert "new_bug.py" not in text


def test_commit_range_semantics_are_unchanged(tmp_path: Path) -> None:
    """Guard — a committed range never picks up untracked working-tree files."""
    repo = _init_repo(tmp_path)
    (repo / "existing.py").write_text("def existing():\n    return 4\n", encoding="utf-8")
    _git(repo, "add", "existing.py")
    _git(repo, "commit", "-m", "tracked change")
    (repo / "new_bug.py").write_text("def bug():\n    return 1 / 0\n", encoding="utf-8")

    text = git_range_diff(cwd=repo, range_spec="main..feature")

    assert "existing.py" in text
    assert "new_bug.py" not in text


def test_gitignored_file_is_excluded(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, gitignore="ignored.py\n")
    (repo / "ignored.py").write_text("def ignored():\n    return 1 / 0\n", encoding="utf-8")

    result = materialize_diff(cwd=repo, out_dir=tmp_path / "out", base="main")

    assert "ignored.py" not in result.path.read_text(encoding="utf-8")
    assert _reports(_limitations(result), "ignored.py")


def test_oversized_untracked_file_is_excluded_and_reported(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "huge.py").write_bytes(b"x = 1\n" + b"# pad\n" * 60_000)

    result = materialize_diff(cwd=repo, out_dir=tmp_path / "out", base="main")

    assert "huge.py" not in result.path.read_text(encoding="utf-8")
    assert _reports(_limitations(result), "huge.py")


def test_binary_untracked_file_is_excluded_and_reported(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "blob.bin").write_bytes(b"\x00\x01\x02\x03")

    result = materialize_diff(cwd=repo, out_dir=tmp_path / "out", base="main")

    assert "blob.bin" not in result.path.read_text(encoding="utf-8")
    assert _reports(_limitations(result), "blob.bin")


def test_symlink_is_excluded(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "target.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "link.py").symlink_to(repo / "target.py")

    result = materialize_diff(cwd=repo, out_dir=tmp_path / "out", base="main")

    assert "link.py" not in result.path.read_text(encoding="utf-8")
    assert _reports(_limitations(result), "link.py")


def test_unicode_quoted_path_is_included(tmp_path: Path) -> None:
    """The path round-trips into the materialized diff (adjacent to residual R5)."""
    repo = _init_repo(tmp_path)
    _git(repo, "config", "core.quotepath", "false")
    (repo / "ünïcode_bug.py").write_text("def bug():\n    return 1 / 0\n", encoding="utf-8")

    result = materialize_diff(cwd=repo, out_dir=tmp_path / "out", base="main")

    assert "ünïcode_bug.py" in result.path.read_text(encoding="utf-8")
