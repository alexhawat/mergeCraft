"""Shared path glob matching for pipeline predicates, analyzers and declared scopes."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import PurePath


def _segment_regex(segment: str) -> str:
    """Translate one ``/``-free glob segment: ``*``, ``?`` and ``[...]`` never cross ``/``."""
    out: list[str] = []
    index = 0
    while index < len(segment):
        char = segment[index]
        index += 1
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[":
            probe = index
            if segment[probe : probe + 1] == "!":
                probe += 1
            if segment[probe : probe + 1] == "]":
                probe += 1
            close = segment.find("]", probe)
            if close == -1:
                out.append(re.escape(char))
                continue
            body = segment[index:close]
            index = close + 1
            negate = body.startswith("!")
            if negate:
                body = body[1:]
            escaped = body.replace("\\", "\\\\").replace("^", "\\^")
            out.append(f"[{'^' if negate else ''}{escaped}]")
        else:
            out.append(re.escape(char))
    return "".join(out)


@lru_cache(maxsize=512)
def _full_match_regex(pattern: str) -> re.Pattern[str]:
    parts = pattern.split("/")
    out: list[str] = []
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        if part == "**":
            # ``**`` is zero or more whole directories; trailing, it is everything below.
            out.append(".*" if last else "(?:[^/]+/)*")
        else:
            out.append(_segment_regex(part) + ("" if last else "/"))
    return re.compile("".join(out))


def path_full_matches_glob(pattern: str, path: str) -> bool:
    """Return whether the whole repo-relative ``path`` matches ``pattern``.

    Anchored at the repository root: ``README.md`` matches only the root file.
    ``*``, ``?`` and ``[...]`` stay inside one segment; a ``**`` segment spans
    zero or more directories (``src/**`` matches ``src/a/b/c.py``, and
    ``src/**/*.py`` matches both ``src/c.py`` and ``src/a/b.py``).

    Args:
        pattern (str): A ``/``-separated glob.
        path (str): A repo-relative path (``\\`` is read as ``/``).

    Returns:
        bool: Whether the path matches.

    Examples:
        >>> path_full_matches_glob("src/**/*.py", "src/c.py")
        True
        >>> path_full_matches_glob("README.md", "docs/README.md")
        False
    """
    normalized = path.replace("\\", "/")
    return _full_match_regex(pattern.replace("\\", "/")).fullmatch(normalized) is not None


def path_matches_glob(pattern: str, path: str) -> bool:
    """Return whether ``path`` matches ``pattern`` (including ``**/`` root fallback).

    Relative patterns match from the right (``PurePath.match``). A pattern with a
    ``**`` segment also matches when it matches the whole path with ``**``
    spanning directories (see :func:`path_full_matches_glob`).
    """
    pure = PurePath(path.replace("\\", "/"))
    pat = pattern.replace("\\", "/")
    if pure.match(pat):
        return True
    if pat.startswith("**/") and pure.match(pat[3:]):
        return True
    if "**" in pat.split("/"):
        return path_full_matches_glob(pat, path)
    return False


__all__ = ["path_full_matches_glob", "path_matches_glob"]
