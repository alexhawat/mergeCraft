"""Bounded repo traversal with gitignore-style exclusions for context retrieval."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path  # noqa: TC003 — used at runtime for repo traversal
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

_EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        ".tox",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".eggs",
        ".hypothesis",
        ".nox",
    }
)


def is_excluded_repo_path(rel_path: str) -> bool:
    """Return whether ``rel_path`` lies under a skipped directory segment."""
    return any(part in _EXCLUDED_DIR_NAMES for part in rel_path.split("/"))


def git_ls_tree_paths(
    repo_root: Path,
    tree_sha: str,
    *,
    suffix: str = "",
) -> list[str]:
    """List tracked paths under ``tree_sha``, applying context exclusions."""
    try:
        completed = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", tree_sha],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        logger.debug("git ls-tree unavailable for tree {}", tree_sha)
        return []
    if completed.returncode != 0:
        logger.debug("git ls-tree failed for tree {}: {}", tree_sha, completed.stderr.strip())
        return []

    paths: list[str] = []
    for rel_path in completed.stdout.splitlines():
        if not rel_path or is_excluded_repo_path(rel_path):
            continue
        if suffix and not rel_path.endswith(suffix):
            continue
        paths.append(rel_path)
    return sorted(paths)


def git_show_text(repo_root: Path, tree_sha: str, rel_path: str) -> str | None:
    """Return file text at ``tree_sha:rel_path``, or ``None`` when absent."""
    try:
        completed = subprocess.run(
            ["git", "show", f"{tree_sha}:{rel_path}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def git_blob_sha(repo_root: Path, tree_sha: str, rel_path: str) -> str:
    """Return the git blob SHA for ``rel_path`` at ``tree_sha``."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", f"{tree_sha}:{rel_path}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        completed = None
    if completed is not None and completed.returncode == 0:
        return completed.stdout.strip()
    shown = git_show_text(repo_root, tree_sha, rel_path)
    if shown is None:
        return f"missing:{tree_sha}:{rel_path}"
    return f"blob:{shown.encode('utf-8').hex()[:40]}"


def iter_repo_files(
    repo_root: Path,
    *,
    predicate: Callable[[Path], bool] | None = None,
    deadline: float | None = None,
) -> Iterator[str]:
    """Walk ``repo_root`` with exclusions and an optional monotonic deadline."""
    for path in sorted(repo_root.rglob("*")):
        if deadline is not None and time.monotonic() > deadline:
            logger.warning("context retrieval scan timed out under {}", repo_root)
            return
        if not path.is_file():
            continue
        rel = path.relative_to(repo_root).as_posix()
        if is_excluded_repo_path(rel):
            continue
        if predicate is not None and not predicate(path):
            continue
        yield rel


__all__ = [
    "git_blob_sha",
    "git_ls_tree_paths",
    "git_show_text",
    "is_excluded_repo_path",
    "iter_repo_files",
]
