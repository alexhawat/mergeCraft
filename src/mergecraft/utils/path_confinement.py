"""Confine untrusted repository paths to a checkout root (MCB-20, D13)."""

from __future__ import annotations

from pathlib import Path


def resolve_confined_path(
    root: str | Path,
    untrusted_path: str,
    *,
    changed_paths: frozenset[str] | None = None,
) -> str:
    """Resolve ``untrusted_path`` inside ``root`` or raise ``ValueError``.

    Rejects absolute paths, traversal, NUL bytes, prefix collisions
    (``/repo`` vs ``/repo2``), symlinks that resolve outside ``root``, and
    (when provided) paths outside ``changed_paths``.
    """
    if "\x00" in untrusted_path:
        msg = "path contains a NUL byte"
        raise ValueError(msg)
    if Path(untrusted_path).is_absolute():
        msg = "absolute paths are not allowed"
        raise ValueError(msg)

    repo_root = Path(root).resolve()
    candidate = (repo_root / untrusted_path).resolve()
    if not _is_under_root(candidate, repo_root):
        msg = f"path {untrusted_path!r} escapes the repository root"
        raise ValueError(msg)
    if not candidate.is_file():
        msg = f"path {untrusted_path!r} is not a file in the checkout"
        raise ValueError(msg)

    relative = candidate.relative_to(repo_root).as_posix()
    if changed_paths is not None and relative not in changed_paths:
        msg = f"path {untrusted_path!r} is not in the changed-path set"
        raise ValueError(msg)
    return str(candidate)


def resolved_within_root(path: Path, root: Path) -> bool:
    """True when ``path``'s resolved location stays inside the resolved ``root``.

    The one reference-resolver rule shared by instruction discovery and the
    agent-security scanner: resolve (following every symlink), then require the
    result to sit under ``root``. A filename is not a location — a symlink whose
    target lives outside the repository is not an in-repo file, however its link
    is named. ``root`` must already be resolved. Any resolution failure counts as
    an escape.
    """
    try:
        path.resolve().relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def _is_under_root(candidate: Path, repo_root: Path) -> bool:
    try:
        candidate.relative_to(repo_root)
    except ValueError:
        return False
    return True


__all__ = ["resolve_confined_path", "resolved_within_root"]
