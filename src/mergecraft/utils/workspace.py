"""Workspace root registry, cwd containment, and safe.directory scoping (W3)."""

from __future__ import annotations

import os
import subprocess
from contextlib import suppress
from pathlib import Path

from loguru import logger

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
        ["git", "config", "--global", "--add", "safe.directory", resolved],
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


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    else:
        return True


def resolve_allowed_working_directory(requested: str | None, *, default: str) -> str:
    """Canonicalize ``requested`` and reject paths outside allowed roots (W3.3)."""
    try:
        default_path = Path(default).resolve()
    except OSError as exc:
        msg = f"invalid default working directory {default!r}: {exc}"
        raise WorkspacePathError(msg) from exc

    if not requested:
        return str(default_path)

    req = Path(requested)
    try:
        resolved = req.resolve() if req.is_absolute() else (default_path / req).resolve()
    except OSError as exc:
        msg = f"working_directory {requested!r} could not be resolved: {exc}"
        raise WorkspacePathError(msg) from exc

    roots = allowed_workspace_roots()
    if default_path not in roots:
        roots.append(default_path)

    for root in roots:
        if _is_under_root(resolved, root):
            return str(resolved)

    msg = (
        f"working_directory {requested!r} is outside allowed workspace roots "
        f"(must stay under $GITHUB_WORKSPACE or a registered cross-repo checkout)"
    )
    raise WorkspacePathError(msg)


__all__ = [
    "WorkspacePathError",
    "add_safe_directory",
    "allowed_workspace_roots",
    "ensure_github_workspace_registered",
    "register_workspace_root",
    "resolve_allowed_working_directory",
]
