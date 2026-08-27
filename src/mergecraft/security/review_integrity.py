"""Post-run integrity helpers for read-only review sessions (MCB-06 / AP5).

Lane C's MCB-19 (AG2) reuses these helpers — import from here rather than
duplicating checkout/config fingerprint logic.

Exports:
    hash_tree: Fingerprint a checkout tree before agent execution.
    verify_tree_unchanged: Fail closed when the tree changed during review.
    assert_checkout_read_boundary: Reject paths outside the checkout read allowlist.
    scan_local_sinks_for_secrets: Detect provider secrets in local log sinks.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_SINK_SUFFIXES: frozenset[str] = frozenset({".log", ".txt", ".jsonl", ".ndjson"})
_SINK_NAMES: frozenset[str] = frozenset({"stdout", "stderr", "output"})


_HASH_EXCLUDE_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        ".mergecraft/prep-scratch",
        ".mergecraft/analyzer-scratch",
        "evidence",
    }
)


def _is_excluded_rel_path(rel: str) -> bool:
    return any(rel == excluded or rel.startswith(f"{excluded}/") for excluded in _HASH_EXCLUDE_DIRS)


def _iter_tree_paths(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    paths: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        if rel_dir != "." and _is_excluded_rel_path(rel_dir):
            dirnames.clear()
            continue
        dirnames[:] = [
            name
            for name in dirnames
            if not _is_excluded_rel_path(Path(dirpath).relative_to(root).joinpath(name).as_posix())
        ]
        for name in dirnames:
            path = Path(dirpath) / name
            if path.is_symlink():
                rel = path.relative_to(root).as_posix()
                if not _is_excluded_rel_path(rel):
                    paths.append(path)
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if _is_excluded_rel_path(rel):
                continue
            paths.append(path)
    return sorted(paths)


def _path_digest_payload(path: Path) -> bytes:
    if path.is_symlink():
        return b"symlink\0" + os.readlink(path).encode()
    return path.read_bytes()


def hash_tree(root: Path) -> str:
    """Return a stable digest of every file under ``root``."""
    resolved = root.resolve()
    digest = hashlib.sha256()
    for path in _iter_tree_paths(resolved):
        rel = path.relative_to(resolved).as_posix()
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(_path_digest_payload(path))
        digest.update(b"\0")
    return digest.hexdigest()


def verify_tree_unchanged(root: Path, before_digest: str) -> None:
    """Raise ``RuntimeError`` when the checkout changed during a read-only review."""
    current = hash_tree(root)
    if current != before_digest:
        msg = f"checkout integrity failure: tree changed during read-only review ({root})"
        raise RuntimeError(msg)


def assert_checkout_read_boundary(checkout: Path, paths: Sequence[Path]) -> None:
    """Raise ``PermissionError`` when any path falls outside ``checkout``."""
    root = checkout.resolve()
    for raw in paths:
        candidate = raw.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as err:
            msg = f"path {candidate} is outside checkout boundary {root}"
            raise PermissionError(msg) from err


def _is_sink_file(path: Path) -> bool:
    if path.suffix.lower() in _SINK_SUFFIXES:
        return True
    return path.name in _SINK_NAMES


def scan_local_sinks_for_secrets(search_root: Path, *, secrets: Sequence[str]) -> str:
    """Return concatenated sink contents that contain any ``secrets`` literal."""
    resolved = search_root.resolve()
    if not resolved.is_dir():
        return ""
    hits: list[str] = []
    for path in sorted(resolved.rglob("*")):
        if not path.is_file() or not _is_sink_file(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(secret and secret in text for secret in secrets):
            hits.append(text)
    return "\n".join(hits)
