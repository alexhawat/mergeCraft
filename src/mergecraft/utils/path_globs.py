"""Shared path glob matching for pipeline predicates and analyzers."""

from __future__ import annotations

from pathlib import PurePath


def path_matches_glob(pattern: str, path: str) -> bool:
    """Return whether ``path`` matches ``pattern`` (including ``**/`` root fallback)."""
    pure = PurePath(path.replace("\\", "/"))
    pat = pattern.replace("\\", "/")
    if pure.match(pat):
        return True
    if pat.startswith("**/"):
        return pure.match(pat[3:])
    return False


__all__ = ["path_matches_glob"]
