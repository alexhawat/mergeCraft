"""Explicit local revisions must agree with the source visible to review tools."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.utils.source_resolve import (
    SourceResolveError,
    SourceResolverSpec,
    materialize_resolved_diff,
    resolve_workspace,
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    _git(root, "init", "-qb", "main")
    (root / "source.py").write_text("value = 1\n")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    _git(root, "checkout", "-qb", "feature")
    (root / "source.py").write_text("value = 2\n")
    _git(root, "commit", "-am", "head", "-q")
    _git(root, "checkout", "-q", "main")
    return root


@pytest.mark.parametrize("selector", [{"head": "feature"}, {"commit_range": "main..feature"}])
def test_other_revision_rejected_until_matching_worktree_is_selected(
    repo: Path, tmp_path: Path, selector: dict[str, str]
) -> None:
    spec = SourceResolverSpec(cwd=repo, base="main", **selector)
    before = _git(repo, "rev-parse", "HEAD")
    with pytest.raises(SourceResolveError, match="clean checkout"):
        materialize_resolved_diff(resolve_workspace(spec), spec=spec, out_dir=tmp_path / "bad")
    assert _git(repo, "rev-parse", "HEAD") == before
    assert (repo / "source.py").read_text() == "value = 1\n"
    selected = tmp_path / "selected"
    _git(repo, "worktree", "add", "-q", str(selected), "feature")
    selected_spec = SourceResolverSpec(repo=str(selected), cwd=repo, base="main", **selector)
    result = materialize_resolved_diff(
        resolve_workspace(selected_spec), spec=selected_spec, out_dir=tmp_path / "good"
    )
    assert "+value = 2" in result.path.read_text()
    assert (selected / "source.py").read_text() == "value = 2\n"


@pytest.mark.parametrize("dirty", ["tracked", "staged", "untracked"])
def test_dirty_explicit_head_is_a_cli_configuration_error(repo: Path, dirty: str) -> None:
    _git(repo, "checkout", "-q", "feature")
    path = repo / ("new.py" if dirty == "untracked" else "source.py")
    path.write_text("value = 3\n")
    if dirty == "staged":
        _git(repo, "add", ".")
    result = CliRunner().invoke(
        app, ["review", "--cwd", str(repo), "--head", "feature", "--base", "main", "--dry-run"]
    )
    assert result.exit_code == 30, result.output
    assert "clean checkout" in result.output
    assert path.read_text() == "value = 3\n"
