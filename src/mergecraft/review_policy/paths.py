"""Repo-relative path normalization for review scope and policy."""

from __future__ import annotations


def normalize_repo_path(path: str) -> str:
    """Normalize repository-relative paths after diff parsing has removed its prefixes."""
    return path.strip().replace("\\", "/").removeprefix("./")


def strip_dot_slash_prefix(path: str) -> str:
    """Remove exactly one leading ``./`` from ``path``.

    ``str.lstrip("./")`` is a character-set strip, not a prefix strip: it removes
    every leading ``.`` and ``/`` character, so ``.github/x.py`` became
    ``github/x.py`` and ``../traces`` became ``traces``. Only one ``./`` prefix is
    removed here, so ``././a`` becomes ``./a``; a leading dot that starts a real
    name, a ``../`` traversal and an absolute path are left untouched.
    """
    return path.removeprefix("./")


__all__ = ["normalize_repo_path", "strip_dot_slash_prefix"]
