"""Unstaged source selection preserves omissions through the review outcome."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mergecraft.utils.source_resolve import (
    ResolvedWorkspace,
    SourceResolverSpec,
    materialize_resolved_diff,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    for args in (
        ["init", "-b", "main"],
        ["config", "user.email", "test@example.com"],
        ["config", "user.name", "Test"],
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    (root / "existing.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, capture_output=True)
    return root


@pytest.mark.parametrize("omission", ["oversized", "binary", "non-UTF-8", "symlink"])
def test_omitted_unstaged_addition_is_not_a_clean_review(
    repo: Path, omission: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.cli.app import app

    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    path = repo / "new.py"
    if omission == "symlink":
        path.symlink_to(repo / "existing.py")
    else:
        content = {"oversized": b"# source\n" * 40_000, "binary": b"\0", "non-UTF-8": b"\xff"}
        path.write_bytes(content[omission])

    result = CliRunner().invoke(app, ["review", "--cwd", str(repo), "--unstaged", "--dry-run"])

    assert result.exit_code == 20, result.output
    output = " ".join(result.output.split())
    assert omission in output
    assert "not reviewed: new.py" in output
    assert "not a clean pass" in output


def test_mixed_unstaged_patch_keeps_both_source_and_omissions(repo: Path, tmp_path: Path) -> None:
    (repo / "new.py").write_bytes(b"\0")
    (repo / "existing.py").write_text("x = 2\n", encoding="utf-8")

    result = materialize_resolved_diff(
        ResolvedWorkspace(cwd=repo, git_common_dir=None, cloned=False),
        spec=SourceResolverSpec(cwd=repo, unstaged=True),
        out_dir=tmp_path / "diff",
    )

    assert not result.empty
    assert "+x = 2" in result.path.read_text(encoding="utf-8")
    assert result.coverage_limitations == ("binary file not reviewed: new.py",)
