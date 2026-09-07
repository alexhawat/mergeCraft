"""Shared ``.env`` path resolution for CLI load and credential writers."""

from __future__ import annotations

import os
from pathlib import Path

from mergecraft.cli.errors import cli_bail
from mergecraft.utils.workspace import git_repo_root


def resolve_local_env_path(
    cwd: Path | None = None,
    *,
    require_repo: bool = True,
) -> Path:
    """Return the local ``.env`` path for load or write.

    Resolution order:

    1. ``$MERGECRAFT_ENV`` if set (tests pin a temp file).
    2. ``<git-repo-root>/.env`` anchored on *cwd* (or the process cwd).

    When ``require_repo`` is False (startup load), invocation outside any git
    repository falls back to ``<cwd>/.env`` so global invocations and CI
    sandboxes stay silent-on-missing. Writers use the default
    ``require_repo=True`` and fail loudly when there is no repository to anchor
    to.
    """
    configured = os.environ.get("MERGECRAFT_ENV")
    if configured:
        return Path(configured).resolve()

    start = (cwd if cwd is not None else Path.cwd()).resolve()
    root = git_repo_root(str(start))
    if root is None:
        if require_repo:
            cli_bail(
                "could not locate the repository root for the local .env — run "
                "from inside the repository, pass --cwd, or point "
                "MERGECRAFT_ENV at the .env you want."
            )
        return start / ".env"
    return root / ".env"
