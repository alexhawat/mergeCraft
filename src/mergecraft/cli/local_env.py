"""Shared ``.env`` path resolution for CLI load and credential writers.

Two anchors, because the CLI has two ways of naming a repository and they are
not interchangeable:

``--cwd`` is documented as "Repository root." and the whole config layer takes
it literally --- :func:`mergecraft.cli.provider_cmd._config_path`,
:func:`mergecraft.cli.config_surface_cmd._config_path`, and
``run_manifest`` all resolve ``<cwd>/.mergecraft/config.yaml`` without walking
up. :func:`local_env_path_for_cwd` matches that so a command cannot read its
registry from one directory and write credentials to another.

Commands with no ``--cwd`` (``auth``, ``tracing logfire``, and the startup
load) have only the process working directory, which may be any subdirectory
of the checkout. :func:`local_env_path_for_process_cwd` walks up to the git
root for those, so the loader and the writers agree on one file.

``$MERGECRAFT_ENV`` wins over both: an operator who pinned an explicit env file
has named the target unambiguously.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from mergecraft.cli.errors import cli_bail
from mergecraft.utils.workspace import git_repo_root

if TYPE_CHECKING:
    OnMissingRepo = Literal["bail", "use-process-cwd"]


def _configured_env_path() -> Path | None:
    """Return ``$MERGECRAFT_ENV`` when set (tests pin a temp file)."""
    configured = os.environ.get("MERGECRAFT_ENV")
    return Path(configured).resolve() if configured else None


def local_env_path_for_cwd(cwd: Path) -> Path:
    """Return the ``.env`` for a command's ``--cwd``, taken literally.

    ``--cwd`` selects the repository the command acts on, and the config layer
    resolves ``<cwd>/.mergecraft/config.yaml`` against that same directory
    without walking up. Anchoring the ``.env`` anywhere else splits the pair:
    ``provider auth --cwd sub/dir`` would read the registry from ``sub/dir``
    and write the credential to the checkout root, and ``provider disable``
    would report a provider disabled in a repository whose registry it never
    read --- the #520 regression, from the other side.

    So this deliberately does *not* walk up to the git root, and it never bails
    on a directory that is not a git checkout: the operator named the directory
    and there is nothing to discover.
    """
    configured = _configured_env_path()
    if configured is not None:
        return configured
    return cwd.resolve() / ".env"


def local_env_path_for_process_cwd(
    *,
    on_missing_repo: OnMissingRepo = "bail",
) -> Path:
    """Return the ``.env`` for a command that has only the process cwd.

    ``auth``, ``tracing logfire``, and the startup load take no ``--cwd``, so
    the process working directory is all they have --- and it is routinely a
    subdirectory of the checkout. Walking up to the git root is what makes the
    loader read the file the writers wrote; anchoring on the raw cwd silently
    wrote a nested ``.env`` that nothing reads and still reported success
    (#221).

    *on_missing_repo* decides what happens outside a git checkout. Writers keep
    the ``"bail"`` default and fail loudly, because there is no root to anchor
    to and a silent write would land somewhere the next invocation cannot find.
    The startup load passes ``"use-process-cwd"`` so a global invocation from
    outside any checkout falls back to ``<cwd>/.env`` and stays
    silent-on-missing (CI sandboxes).
    """
    configured = _configured_env_path()
    if configured is not None:
        return configured

    start = Path.cwd().resolve()
    root = git_repo_root(str(start))
    if root is None:
        if on_missing_repo == "bail":
            cli_bail(
                f"could not locate a git repository root at {start} for the "
                "local .env — run mergecraft from inside the repository, or "
                "point MERGECRAFT_ENV at the .env you want written."
            )
        return start / ".env"
    return root / ".env"


__all__ = ["local_env_path_for_cwd", "local_env_path_for_process_cwd"]
