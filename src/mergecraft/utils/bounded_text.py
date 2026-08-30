"""Bounded UTF-8 text reads for indexers and cross-repo traversal."""

from __future__ import annotations

from collections.abc import Iterator  # noqa: TC003 — used in iter_indexable_files
from pathlib import Path  # noqa: TC003 — used at runtime for path containment

MAX_INDEX_TEXT_BYTES = 256_000
MAX_CONSUMER_HAYSTACK_BYTES = 2_048_000
MAX_RENDER_TEXT_CHARS = 200


def truncate_text(text: str, max_chars: int = MAX_RENDER_TEXT_CHARS) -> str:
    """Truncate ``text`` for log rendering without splitting multibyte codepoints."""
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}…"


def read_bounded_text(path: Path, *, max_bytes: int = MAX_INDEX_TEXT_BYTES) -> str | None:
    """Read UTF-8 text with replacement errors, skipping symlinks and oversized files."""
    if path.is_symlink() or not path.is_file():
        return None
    try:
        if path.stat().st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def resolve_path_under_root(root: Path, relative_path: str) -> Path:
    """Resolve ``relative_path`` under ``root`` or raise ``FileNotFoundError``."""
    root_resolved = root.resolve()
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        msg = f"linked repo path escapes checkout root: {relative_path!r}"
        raise FileNotFoundError(msg) from exc
    if target.is_symlink():
        msg = f"linked repo path is a symlink: {relative_path!r}"
        raise FileNotFoundError(msg)
    return target


def iter_indexable_files(root: Path) -> Iterator[Path]:
    """Yield regular files under ``root``, skipping symlinks and ``.git`` trees."""
    root_resolved = root.resolve()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if ".git" in path.parts:
            continue
        try:
            path.resolve().relative_to(root_resolved)
        except ValueError:
            continue
        yield path


__all__ = [
    "MAX_CONSUMER_HAYSTACK_BYTES",
    "MAX_INDEX_TEXT_BYTES",
    "MAX_RENDER_TEXT_CHARS",
    "iter_indexable_files",
    "read_bounded_text",
    "resolve_path_under_root",
    "truncate_text",
]
