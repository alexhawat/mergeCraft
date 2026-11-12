"""Resolve the target branch a branch-level CLI preview diffs against.

Module: mergecraft.cli.diff_base
Depends: mergecraft.utils.git_hardening, mergecraft.utils.offline_diff

``describe`` and ``plan`` summarize the work on the current branch. The
review default base prefers ``@{upstream}``, but after ``git push -u origin
feature`` that upstream is the branch's own remote copy, so the merge-base diff
is empty. These commands want the branch the work will merge into instead.

Exports:
    Functions:
        target_base — Ref of the branch the current branch's work merges into.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from mergecraft.utils.git_hardening import git_argv
from mergecraft.utils.offline_diff import detect_default_base

if TYPE_CHECKING:
    from pathlib import Path

_CANDIDATE_BRANCHES = ("main", "master", "develop", "trunk")
_GIT_TIMEOUT_S = 15


def _git(cwd: Path, *args: str) -> str | None:
    """Run one read-only git command; return stripped stdout, or ``None`` on failure.

    Args:
        cwd (Path): Repository directory.
        *args (str): git arguments.

    Returns:
        str | None: Output, or ``None`` when git fails or prints nothing.
    """
    try:
        completed = subprocess.run(
            git_argv(list(args)),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = completed.stdout.strip()
    return out if completed.returncode == 0 and out else None


def _branch_name(ref: str) -> str:
    """Return the branch part of ``remote/branch`` (or *ref* unchanged).

    Args:
        ref (str): A short ref such as ``origin/main`` or ``main``.

    Returns:
        str: The branch name after the first ``/``.
    """
    return ref.split("/", 1)[1] if "/" in ref else ref


def target_base(cwd: Path) -> str:
    """Return the ref the current branch's work merges into.

    Order: an upstream that tracks a *different* branch (an operator who set
    ``feature`` to track ``origin/main`` chose that base); the remote's default
    branch (``origin/HEAD``); ``origin/main|master|develop|trunk`` then the
    local names, skipping the current branch itself; finally the review default
    (``HEAD^`` in a fresh repository).

    Args:
        cwd (Path): Repository directory.

    Returns:
        str: A ref for ``git diff --merge-base``.

    Raises:
        RuntimeError: When no base can be found (from the review default).
    """
    current = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    upstream = _git(cwd, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if upstream and _branch_name(upstream) != current:
        return upstream
    remote_head = _git(cwd, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if remote_head and _branch_name(remote_head) != current:
        return remote_head
    for name in _CANDIDATE_BRANCHES:
        if name == current:
            continue
        for candidate in (f"origin/{name}", name):
            if _git(cwd, "rev-parse", "--verify", "--quiet", candidate):
                return candidate
    return detect_default_base(cwd)


__all__ = ["target_base"]
