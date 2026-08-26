"""Workspace root registry, cwd containment, and safe.directory scoping (W3)."""

from __future__ import annotations

import os
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from mergecraft.utils.git_hardening import git_argv

if TYPE_CHECKING:
    from collections.abc import Sequence

_workspace_roots: set[str] = set()
_safe_directories_added: set[str] = set()


class WorkspacePathError(ValueError):
    """Raised when a requested cwd escapes allowed workspace roots."""


def register_workspace_root(path: str) -> None:
    """Record an allowed workspace root and mark it safe for git (W3.1/W3.3)."""
    try:
        resolved = str(Path(path).resolve())
    except OSError:
        resolved = path
    if resolved in _workspace_roots:
        return
    _workspace_roots.add(resolved)
    add_safe_directory(resolved)
    logger.debug("registered workspace root {}", resolved)


def add_safe_directory(path: str) -> None:
    """Add a single path to git's global ``safe.directory`` list (W3.1)."""
    try:
        resolved = str(Path(path).resolve())
    except OSError:
        resolved = path
    if resolved in _safe_directories_added:
        return
    subprocess.run(
        git_argv(["config", "--global", "--add", "safe.directory", resolved]),
        check=False,
        capture_output=True,
        text=True,
    )
    _safe_directories_added.add(resolved)


def ensure_github_workspace_registered() -> None:
    """Register ``$GITHUB_WORKSPACE`` when present (W3.1)."""
    workspace = os.environ.get("GITHUB_WORKSPACE", "").strip()
    if workspace:
        register_workspace_root(workspace)


def allowed_workspace_roots() -> list[Path]:
    """Return resolved paths that may host agent or shell working directories."""
    roots: list[Path] = []
    for raw in _workspace_roots:
        with suppress(OSError):
            roots.append(Path(raw).resolve())
    workspace = os.environ.get("GITHUB_WORKSPACE", "").strip()
    if workspace:
        with suppress(OSError):
            roots.append(Path(workspace).resolve())
    # Stable dedupe while preserving order.
    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def git_repo_root(start: str | None = None) -> Path | None:
    """Resolve the git work-tree root containing *start*, or ``None``.

    The single spelling of ``git rev-parse --show-toplevel`` in ``src/``. Every
    failure mode — not a repository, no ``git`` on PATH, the call timing out —
    collapses to ``None`` so callers decide whether a missing root is fatal.
    """
    try:
        completed = subprocess.run(
            git_argv(["rev-parse", "--show-toplevel"]),
            cwd=start,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):  # fmt: skip
        return None
    top = completed.stdout.strip()
    if completed.returncode != 0 or not top:
        return None
    try:
        return Path(top).resolve()
    except OSError:
        return None


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    else:
        return True


def resolve_allowed_working_directory(requested: str | None, *, default: str) -> str:
    """Canonicalize a requested cwd under :func:`confine_to_workspace` (W3.3).

    A cwd-shaped adapter over the single containment rule: ``None`` means "stay
    where you are", and the failure is reported against ``working_directory``
    because that is the argument the caller actually supplied.

    Raises:
        WorkspacePathError: when *requested* resolves outside the allowed roots.
    """
    try:
        default_path = Path(default).resolve()
    except OSError as exc:
        msg = f"invalid default working directory {default!r}: {exc}"
        raise WorkspacePathError(msg) from exc

    if not requested:
        return str(default_path)

    try:
        return str(confine_to_workspace(requested, base=str(default_path)))
    except WorkspacePathError as exc:
        msg = (
            f"working_directory {requested!r} is outside allowed workspace roots "
            f"(must stay under $GITHUB_WORKSPACE or a registered cross-repo checkout)"
        )
        raise WorkspacePathError(msg) from exc


def confine_to_workspace(
    value: str,
    *,
    base: str,
    extra_roots: Sequence[str] = (),
) -> Path:
    """Resolve *value* and require it to sit under an allowed workspace root.

    The single containment rule for every tool that accepts a path. Two things it
    fixes over a hand-rolled prefix test:

    - A relative value is resolved against *base* — the directory the command
      will actually run in — not the MCP server's process cwd, which in the
      Action is not the checkout.
    - Every root registered by a cross-repo checkout is allowed, not only the
      primary repo, so a secondary checkout is reachable at all.

    Raises:
        WorkspacePathError: when the resolved path is under none of the roots.
    """
    try:
        base_path = Path(base).resolve()
    except OSError as exc:
        msg = f"invalid base directory {base!r}: {exc}"
        raise WorkspacePathError(msg) from exc

    candidate = Path(value)
    try:
        resolved = (
            candidate.resolve() if candidate.is_absolute() else (base_path / candidate).resolve()
        )
    except OSError as exc:
        msg = f"path {value!r} could not be resolved: {exc}"
        raise WorkspacePathError(msg) from exc

    roots = [base_path, *allowed_workspace_roots()]
    for raw in extra_roots:
        if not raw:
            continue
        with suppress(OSError):
            roots.append(Path(raw).resolve())

    for root in roots:
        if _is_under_root(resolved, root):
            return resolved

    msg = (
        f"path {value!r} is outside the allowed workspace roots "
        "(the repo checkout, a registered cross-repo checkout, or the session tmpdir)"
    )
    raise WorkspacePathError(msg)


__all__ = [
    "WorkspacePathError",
    "add_safe_directory",
    "allowed_workspace_roots",
    "confine_to_workspace",
    "ensure_github_workspace_registered",
    "git_repo_root",
    "register_workspace_root",
    "resolve_allowed_working_directory",
]
