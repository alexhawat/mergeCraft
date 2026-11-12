"""``review --staged --unstaged`` reviews every uncommitted change (#1341)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.utils.source_resolve import (
    ResolvedWorkspace,
    SourceResolverSpec,
    materialize_resolved_diff,
)

_ENV = {"NO_COLOR": "1", "TERM": "dumb"}


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with one staged edit, one unstaged edit and one untracked file."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "staged.py").write_text("a = 1\n", encoding="utf-8")
    (root / "unstaged.py").write_text("b = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    (root / "staged.py").write_text("a = 2\n", encoding="utf-8")
    _git(root, "add", "staged.py")
    (root / "unstaged.py").write_text("b = 2\n", encoding="utf-8")
    (root / "untracked.py").write_text("c = 3\n", encoding="utf-8")
    return root


def _materialize(root: Path, tmp_path: Path, **flags: bool) -> str:
    result = materialize_resolved_diff(
        ResolvedWorkspace(cwd=root, git_common_dir=None, cloned=False),
        spec=SourceResolverSpec(cwd=root, **flags),
        out_dir=tmp_path / "diff",
    )
    return result.path.read_text(encoding="utf-8")


def test_combined_flags_include_staged_unstaged_and_untracked(repo: Path, tmp_path: Path) -> None:
    """Both flags together yield the union of the two selections."""
    text = _materialize(repo, tmp_path, staged=True, unstaged=True)

    assert "+a = 2" in text
    assert "+b = 2" in text
    assert "+c = 3" in text


def test_combined_flags_on_a_file_staged_then_edited_again(repo: Path, tmp_path: Path) -> None:
    """A file with staged and unstaged edits appears once, at its working-tree content."""
    (repo / "staged.py").write_text("a = 3\n", encoding="utf-8")

    text = _materialize(repo, tmp_path, staged=True, unstaged=True)

    assert text.count("+++ b/staged.py") == 1
    assert "+a = 3" in text
    assert "+a = 2" not in text


def test_combined_flags_before_the_first_commit(tmp_path: Path) -> None:
    """An unborn branch still yields the staged and untracked files."""
    root = tmp_path / "fresh"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "staged.py").write_text("a = 1\n", encoding="utf-8")
    _git(root, "add", "staged.py")
    (root / "untracked.py").write_text("c = 1\n", encoding="utf-8")

    text = _materialize(root, tmp_path, staged=True, unstaged=True)

    assert "+a = 1" in text
    assert "+c = 1" in text


def test_review_with_both_flags_does_not_pass_on_an_empty_diff(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With nothing staged, the CLI dry run still reviews the unstaged edits."""
    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    _git(repo, "reset", "-q", "staged.py")

    result = CliRunner().invoke(
        app,
        ["review", "--cwd", str(repo), "--staged", "--unstaged", "--dry-run"],
        env=_ENV,
    )

    combined = result.stdout + result.stderr
    assert "empty diff" not in combined, combined
    assert "(0 lines)" not in combined, combined
