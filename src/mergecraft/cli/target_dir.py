"""Resolve the working directory for CLI commands that take ``--cwd``."""

from __future__ import annotations

from pathlib import Path


def target_dir(cwd: Path) -> Path:
    """The directory this command operates on — ``cwd``, resolved.

    Deliberately not ``git_repo_root``: these commands act on whatever tree they
    are pointed at, including one that is not a git checkout at all. Named for
    that so it cannot be mistaken for the canonical repo-root helper in
    ``utils/workspace.py``.
    """
    return cwd.resolve()
