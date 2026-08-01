"""Tests for checkout_pr base-ref helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

from mergecraft.mcp.checkout import ensure_local_base_branch_alias


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_origin_with_base(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "README.md").write_text("base\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", "base")
    _git(work, "branch", "-M", "pre-0.0.1")
    _git(work, "clone", "--bare", str(work), str(origin))
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(origin), str(clone))
    return clone


def test_ensure_local_base_branch_alias_creates_bare_base_name(tmp_path: Path) -> None:
    repo = _init_origin_with_base(tmp_path)
    _git(repo, "checkout", "-b", "pr-1")
    ensure_local_base_branch_alias(cwd=str(repo), base_ref="pre-0.0.1")
    shown = subprocess.check_output(
        ["git", "show", "pre-0.0.1:README.md"],
        cwd=repo,
        text=True,
    )
    assert shown == "base\n"


def test_ensure_local_base_branch_alias_noop_when_base_already_resolves(tmp_path: Path) -> None:
    repo = _init_origin_with_base(tmp_path)
    ensure_local_base_branch_alias(cwd=str(repo), base_ref="pre-0.0.1")
    shown = subprocess.check_output(
        ["git", "show", "pre-0.0.1:README.md"],
        cwd=repo,
        text=True,
    )
    assert shown == "base\n"


def test_ensure_local_base_branch_alias_noop_on_empty_ref(tmp_path: Path) -> None:
    repo = _init_origin_with_base(tmp_path)
    ensure_local_base_branch_alias(cwd=str(repo), base_ref="")
