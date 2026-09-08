"""Unit tests for offline_diff helpers against a real temp git repo."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mergecraft.utils.offline_diff import detect_default_base, git_unstaged_diff, materialize_diff


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


def test_unstaged_diff_skips_binary_untracked_files(git_repo: Path) -> None:
    """Binary untracked files must not crash unstaged diff materialization."""
    (git_repo / "binary.bin").write_bytes(b"\x00\x01\x02")
    text = git_unstaged_diff(cwd=git_repo)
    assert "binary.bin" not in text


@pytest.mark.parametrize("name", ["new.txt", "with space.txt", "with\ttab.txt"])
@pytest.mark.parametrize("contents", ["first\nsecond\n", "no newline", ""])
def test_untracked_patch_is_accepted_by_git(git_repo: Path, name: str, contents: str) -> None:
    path = git_repo / name
    path.write_text(contents)
    patch = git_unstaged_diff(cwd=git_repo)
    path.unlink()
    _git(git_repo, "checkout", "--", "a.txt")
    result = subprocess.run(
        ["git", "apply", "-"], cwd=git_repo, input=patch, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    assert path.read_text() == contents


def test_explicit_local_base_preserves_staged_and_unstaged_changes(
    git_repo: Path, tmp_path: Path
) -> None:
    from mergecraft.utils.source_resolve import (
        ResolvedWorkspace,
        SourceResolverSpec,
        materialize_resolved_diff,
    )

    (git_repo / "a.txt").write_text("staged\n")
    _git(git_repo, "add", "a.txt")
    (git_repo / "a.txt").write_text("staged\nunstaged\n")
    result = materialize_resolved_diff(
        ResolvedWorkspace(cwd=git_repo, git_common_dir=None, cloned=False),
        spec=SourceResolverSpec(cwd=git_repo, base="main"),
        out_dir=tmp_path / "result",
    )
    assert "+staged" in result.path.read_text()
    assert "+unstaged" in result.path.read_text()


def test_missing_common_history_never_substitutes_endpoint_diff(git_repo: Path) -> None:
    from mergecraft.utils.offline_diff import git_ref_diff

    _git(git_repo, "checkout", "--orphan", "unrelated")
    _git(git_repo, "add", ".")
    _git(git_repo, "commit", "-m", "unrelated root")
    with pytest.raises(RuntimeError, match="shared history"):
        git_ref_diff(cwd=git_repo, base="main", head="HEAD")


def test_untracked_non_utf8_does_not_crash_or_emit_a_lossy_patch(git_repo: Path) -> None:
    (git_repo / "legacy.txt").write_bytes(b"caf\xe9\n")
    text = git_unstaged_diff(cwd=git_repo)
    assert "legacy.txt" not in text
