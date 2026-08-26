"""Lane A AP1.1 — root-side git must not execute hostile ``.git/config`` (MCB-01)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mergecraft.mcp.git import _run_git
from mergecraft.xrepo.review import _rev_parse_commit
from tests.security.hostile_git_fixtures import HostileGitRepo, build_hostile_git_repo


def test_root_side_status_does_not_execute_fsmonitor(hostile_git_repo: HostileGitRepo) -> None:
    _run_git(["status", "--porcelain"], cwd=str(hostile_git_repo.root))
    assert not hostile_git_repo.fsmonitor_sentinel.exists()


def test_root_side_diff_does_not_execute_diff_external(hostile_git_repo: HostileGitRepo) -> None:
    _run_git(["diff", "HEAD"], cwd=str(hostile_git_repo.root))
    assert not hostile_git_repo.diff_external_sentinel.exists()


def test_commit_path_does_not_execute_fsmonitor(hostile_git_repo: HostileGitRepo) -> None:
    """``commit_changes`` path must pin safe git config (hooksPath alone is insufficient)."""
    (hostile_git_repo.root / "tracked.txt").write_text("x\n", encoding="utf-8")
    _run_git(["add", "tracked.txt"], cwd=str(hostile_git_repo.root))
    _run_git(["commit", "-m", "test"], cwd=str(hostile_git_repo.root))
    assert not hostile_git_repo.fsmonitor_sentinel.exists()


def test_insteadof_rewrite_does_not_leak_git_config_value_0(
    hostile_git_repo: HostileGitRepo,
) -> None:
    completed = subprocess.run(
        ["git", "config", "--get", "url.https://attacker.example/.insteadof"],
        cwd=hostile_git_repo.root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.stdout.strip() == "https://github.com/"
    _run_git(["status"], cwd=str(hostile_git_repo.root))
    assert not hostile_git_repo.fsmonitor_sentinel.exists()


def test_xrepo_checkout_is_equally_protected(hostile_git_repo: HostileGitRepo) -> None:
    """H-7: xrepo ``_rev_parse_commit`` must use hardened git argv."""
    _rev_parse_commit(hostile_git_repo.root, "HEAD")
    assert not hostile_git_repo.fsmonitor_sentinel.exists()


@pytest.fixture
def hostile_git_repo(tmp_path: Path) -> HostileGitRepo:
    return build_hostile_git_repo(tmp_path)
