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
        materialize_branch_diff — Materialize the branch diff; a bad ``--base`` exits 30.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import typer

from mergecraft.cli.consoles import err_console
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE
from mergecraft.utils.git_hardening import git_argv
from mergecraft.utils.offline_diff import detect_default_base, materialize_diff

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.utils.offline_diff import DiffMaterialization

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
    branch (``origin/HEAD``); on a feature branch, ``origin/main|master|develop|
    trunk`` then the local names; otherwise (including on a base branch such as
    ``main`` itself) the review default (``HEAD^`` in a fresh repository).

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
    if current in _CANDIDATE_BRANCHES:
        # On a base branch itself (``main``) with no remote HEAD, a sibling such
        # as ``develop`` is not what this work merges into: keep the review default.
        return detect_default_base(cwd)
    for name in _CANDIDATE_BRANCHES:
        for candidate in (f"origin/{name}", name):
            if _git(cwd, "rev-parse", "--verify", "--quiet", candidate):
                return candidate
    return detect_default_base(cwd)


def materialize_branch_diff(*, cwd: Path, out_dir: Path, base: str | None) -> DiffMaterialization:
    """Write the branch diff for ``describe`` / ``plan`` under *out_dir*.

    An explicit ``--base`` that cannot be diffed prints one error line and exits
    with the configuration code; a failing default base is re-raised for the
    caller to handle.

    Args:
        cwd (Path): Repository root.
        out_dir (Path): Directory that receives ``review.diff``.
        base (str | None): Explicit ``--base`` ref, or ``None`` for :func:`target_base`.

    Returns:
        DiffMaterialization: The written diff and its base ref.

    Raises:
        typer.Exit: When an explicit *base* cannot be diffed.
    """
    try:
        resolved = base if base is not None else target_base(cwd)
        return materialize_diff(cwd=cwd, out_dir=out_dir, base=resolved)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        if base is None:
            raise
        detail = " ".join(str(exc).split())
        err_console.print(
            f"could not diff against --base {base!r}: {detail}",
            style="red",
            markup=False,
            highlight=False,
            soft_wrap=True,
        )
        raise typer.Exit(CLI_CONFIGURATION_EXIT_CODE) from exc


__all__ = ["materialize_branch_diff", "target_base"]
