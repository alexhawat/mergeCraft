"""Repository confinement for changed agent manifests.

Module: mergecraft.analyzers.agentsec.confinement
Depends: mergecraft.utils.path_confinement, loguru

Exports:
    Functions:
        confined_changed_file — Return a changed file's path only when it resolves inside the repo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from mergecraft.utils.path_confinement import resolved_within_root

if TYPE_CHECKING:
    from pathlib import Path


def confined_changed_file(
    repo_root: Path,
    rel: str,
    *,
    refusals: list[str] | None = None,
) -> Path | None:
    """Return ``repo_root / rel`` when it is a regular file that resolves inside the repo.

    ``None`` means "not a file to scan": either it does not exist as a file, or it
    resolves outside ``repo_root`` (a symlink — or a symlinked parent directory —
    pointing out of the checkout). A refusal is logged and, when ``refusals`` is
    given, recorded as ``rel`` so the caller can report it. The refused file is
    never opened: the check is on the resolved location, before any read.
    """
    path = repo_root / rel
    if not path.is_file():
        return None
    if not resolved_within_root(path, repo_root.resolve()):
        logger.debug("agentsec: refusing {} — it resolves outside the repository root", rel)
        if refusals is not None:
            refusals.append(rel)
        return None
    return path


__all__ = ["confined_changed_file"]
