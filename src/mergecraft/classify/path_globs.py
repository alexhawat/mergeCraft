"""Linear-time path glob matching (#1056 part 3).

Declared scope globs come from an untrusted pull request body, so matching must
stay fast on any glob the parser accepts. Nothing here compiles a regular
expression or calls ``fnmatch`` / ``PurePath.match``: both backtrack
exponentially on globs such as ``**/**/**/…/zz`` or ``*a*a*a…*b``.

A glob and a path are split on ``/``. A ``**`` segment matches zero or more
whole segments; inside one segment ``*`` matches any run of characters, ``?``
one character and ``[…]`` one character from a class (``[!…]`` negates). Both
levels use the greedy wildcard algorithm with one backtrack point, which is
O(len(pattern) * len(text)) in the worst case and never exponential.

This module is a leaf (it imports nothing from ``mergecraft``) so the
classifier can use it without pulling in ``mergecraft.utils``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Final

_STAR: Final = "*"
_ANY: Final = "?"
_DOUBLE_STAR: Final = "**"

# A segment token: ``_STAR``, ``_ANY``, a one-character literal ``("=", ch)`` or a
# class ``("[", negate, singles, ranges)``.
_Token = str | tuple[str, str] | tuple[str, bool, frozenset[str], tuple[tuple[str, str], ...]]


def _parse_class(segment: str, start: int) -> tuple[_Token, int] | None:
    """Parse ``[…]`` at ``segment[start]``; ``None`` when it never closes (a literal ``[``)."""
    index = start + 1
    negate = segment[index : index + 1] == "!"
    if negate:
        index += 1
    body_start = index
    if segment[index : index + 1] == "]":
        index += 1
    close = segment.find("]", index)
    if close == -1:
        return None
    body = segment[body_start:close]
    singles: set[str] = set()
    ranges: list[tuple[str, str]] = []
    position = 0
    while position < len(body):
        if position + 2 < len(body) and body[position + 1] == "-":
            ranges.append((body[position], body[position + 2]))
            position += 3
        else:
            singles.add(body[position])
            position += 1
    return ("[", negate, frozenset(singles), tuple(ranges)), close + 1


@lru_cache(maxsize=1024)
def _segment_tokens(segment: str) -> tuple[_Token, ...]:
    tokens: list[_Token] = []
    index = 0
    while index < len(segment):
        char = segment[index]
        if char == "*":
            if not tokens or tokens[-1] != _STAR:  # ``**`` inside a segment is one ``*``
                tokens.append(_STAR)
            index += 1
        elif char == "?":
            tokens.append(_ANY)
            index += 1
        elif char == "[" and (parsed := _parse_class(segment, index)) is not None:
            token, index = parsed
            tokens.append(token)
        else:
            tokens.append(("=", char))
            index += 1
    return tuple(tokens)


def _token_matches(token: _Token, char: str) -> bool:
    if token == _ANY:
        return True
    if isinstance(token, tuple) and token[0] == "=":
        return token[1] == char
    if isinstance(token, tuple) and len(token) == 4:
        _kind, negate, singles, ranges = token
        hit = char in singles or any(low <= char <= high for low, high in ranges)
        return hit is not negate
    return False


def _segment_matches(pattern: str, text: str) -> bool:
    """Whether one ``/``-free ``text`` matches one glob segment (greedy, one backtrack point)."""
    tokens = _segment_tokens(pattern)
    t_index = s_index = 0
    star_token = -1
    star_text = 0
    while s_index < len(text):
        if t_index < len(tokens) and tokens[t_index] == _STAR:
            star_token, star_text = t_index, s_index
            t_index += 1
        elif t_index < len(tokens) and _token_matches(tokens[t_index], text[s_index]):
            t_index += 1
            s_index += 1
        elif star_token != -1:
            star_text += 1
            t_index, s_index = star_token + 1, star_text
        else:
            return False
    while t_index < len(tokens) and tokens[t_index] == _STAR:
        t_index += 1
    return t_index == len(tokens)


def _split(value: str) -> list[str]:
    """``/``-separated segments with empty and ``.`` segments dropped; a leading ``/`` is kept."""
    normalized = value.replace("\\", "/")
    segments = [part for part in normalized.split("/") if part not in {"", "."}]
    return ["/", *segments] if normalized.startswith("/") else segments


def _pattern_segments(pattern: str) -> list[str]:
    collapsed: list[str] = []
    for part in _split(pattern):
        if part == _DOUBLE_STAR and collapsed and collapsed[-1] == _DOUBLE_STAR:
            continue
        collapsed.append(part)
    return collapsed


def _segments_match(pattern: list[str], path: list[str]) -> bool:
    """Greedy match where a ``**`` pattern segment spans zero or more path segments."""
    p_index = s_index = 0
    star_pattern = -1
    star_path = 0
    while s_index < len(path):
        if p_index < len(pattern) and pattern[p_index] == _DOUBLE_STAR:
            star_pattern, star_path = p_index, s_index
            p_index += 1
        elif (
            p_index < len(pattern)
            and pattern[p_index] != "/"
            and path[s_index] != "/"
            and _segment_matches(pattern[p_index], path[s_index])
        ) or (p_index < len(pattern) and pattern[p_index] == "/" == path[s_index]):
            p_index += 1
            s_index += 1
        elif star_pattern != -1:
            star_path += 1
            p_index, s_index = star_pattern + 1, star_path
        else:
            return False
    while p_index < len(pattern) and pattern[p_index] == _DOUBLE_STAR:
        p_index += 1
    return p_index == len(pattern)


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
        bool: Whether the path matches; an empty pattern matches nothing.

    Examples:
        >>> path_full_matches_glob("src/**/*.py", "src/c.py")
        True
        >>> path_full_matches_glob("README.md", "docs/README.md")
        False
    """
    segments = _pattern_segments(pattern)
    if not segments:
        return False
    return _segments_match(segments, _split(path))


def path_matches_glob(pattern: str, path: str) -> bool:
    """Return whether ``path`` matches ``pattern``, matching a relative pattern from the right.

    A relative pattern matches when it matches the path's trailing segments
    (``*.py`` matches ``src/a.py``; ``**/x`` also matches ``x``); a pattern with a
    leading ``/`` matches the whole path only. A ``**`` segment spans zero or
    more directories.

    Args:
        pattern (str): A ``/``-separated glob.
        path (str): A path (``\\`` is read as ``/``).

    Returns:
        bool: Whether the path matches; an empty pattern matches nothing.
    """
    segments = _pattern_segments(pattern)
    if not segments:
        return False
    if segments[0] != "/" and segments[0] != _DOUBLE_STAR:
        segments = [_DOUBLE_STAR, *segments]
    return _segments_match(segments, _split(path))


__all__ = ["path_full_matches_glob", "path_matches_glob"]
