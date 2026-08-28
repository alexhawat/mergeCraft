"""Resolve the installed build commit SHA for version display."""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

from mergecraft._build_metadata import __commit__ as _baked_commit
from mergecraft.utils.git_hardening import git_argv


@lru_cache(maxsize=1)
def resolve_build_commit() -> str | None:
    """Return the full git SHA baked at build time, or from a source checkout."""
    env_commit = os.environ.get("MERGECRAFT_BUILD_COMMIT", "").strip()
    if env_commit:
        return env_commit
    if _baked_commit:
        return _baked_commit
    return _git_head_commit(_package_root())


def _package_root() -> Path:
    return Path(__file__).resolve().parent


def _git_head_commit(root: Path) -> str | None:
    for candidate in (root, *root.parents):
        if (candidate / ".git").exists():
            root = candidate
            break
    else:
        return None
    try:
        output = subprocess.check_output(
            git_argv(["rev-parse", "HEAD"]),
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    commit = output.strip()
    return commit or None


__all__ = ["resolve_build_commit"]
