"""Pinned git argv for root-side subprocess invocations (MCB-01 / D2).

Every mergeCraft process that shells out to ``git`` while still privileged must
route through :func:`git_argv` so agent-writable ``.git/config`` cannot execute
hooks, fsmonitor, diff drivers, or other config-driven side effects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

GIT_SAFE_CONFIG: Final[tuple[str, ...]] = (
    "-c",
    "core.fsmonitor=false",
    "-c",
    "diff.external=",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "uploadpack.packObjectsHook=",
    "-c",
    "core.sshCommand=ssh",
    "-c",
    "core.gitProxy=",
    "-c",
    "protocol.ext.allow=never",
    "-c",
    "core.pager=cat",
)


def git_argv(args: Sequence[str]) -> list[str]:
    """Return ``git`` argv with every safe-config pin prepended before *args*."""
    return ["git", *GIT_SAFE_CONFIG, *args]


__all__ = ["GIT_SAFE_CONFIG", "git_argv"]
