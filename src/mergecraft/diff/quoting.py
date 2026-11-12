"""Git path quoting: decode C-quoted paths and split ``diff --git`` header bodies.

Git wraps a path in double quotes and escapes it C-style when the path holds a
quote, a backslash, a control character or (with the default
``core.quotePath=true``) any non-ASCII byte: ``café.md`` is written
``"caf\\303\\251.md"``. A path that only contains spaces is *not* quoted, so a
header body cannot be split on whitespace either. Every diff reader in mergeCraft
decodes paths through this module so a file has one name everywhere.

Exports:
    unquote_git_path: Decode one possibly-quoted path token.
    split_diff_git_paths: Split ``a/<old> b/<new>`` into the two decoded paths.
"""

from __future__ import annotations

import re

_A_PREFIX = "a/"
_B_PREFIX = "b/"
_HEADER_SEPARATOR_RE = re.compile(r' (?=b/|"b/)')

_C_ESCAPES: dict[str, int] = {
    "a": 0x07,
    "b": 0x08,
    "f": 0x0C,
    "n": 0x0A,
    "r": 0x0D,
    "t": 0x09,
    "v": 0x0B,
    '"': 0x22,
    "\\": 0x5C,
}
_OCTAL_DIGITS = frozenset("01234567")


def unquote_git_path(token: str) -> str | None:
    """Decode a Git C-style quoted path, or return an unquoted token unchanged.

    The decoded bytes are interpreted as UTF-8.

    Args:
        token (str): One path token as Git printed it.

    Returns:
        str | None: The decoded path, or ``None`` for malformed quoting or bytes
        that are not valid UTF-8.

    Examples:
        >>> unquote_git_path('"caf\\\\303\\\\251.md"')
        'café.md'
        >>> unquote_git_path("my notes.txt")
        'my notes.txt'
    """
    if not token.startswith('"'):
        return token
    if len(token) < 2 or not token.endswith('"'):
        return None
    body = token[1:-1]
    out = bytearray()
    index = 0
    length = len(body)
    while index < length:
        char = body[index]
        if char != "\\":
            out.extend(char.encode("utf-8"))
            index += 1
            continue
        index += 1
        if index >= length:
            return None
        escape = body[index]
        mapped = _C_ESCAPES.get(escape)
        if mapped is not None:
            out.append(mapped)
            index += 1
            continue
        if escape in _OCTAL_DIGITS:
            octal = body[index : index + 3]
            if len(octal) != 3 or any(digit not in _OCTAL_DIGITS for digit in octal):
                return None
            out.append(int(octal, 8) & 0xFF)
            index += 3
            continue
        return None
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _take_quoted_token(text: str) -> tuple[str | None, str]:
    """Split a leading C-quoted token from ``text`` and decode it."""
    if not text.startswith('"'):
        return None, text
    index = 1
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == '"':
            return unquote_git_path(text[: index + 1]), text[index + 1 :]
        index += 1
    return None, text


def split_diff_git_paths(body: str) -> tuple[str, str] | None:
    """Split the body of a ``diff --git`` header into ``(old, new)`` paths.

    Spaces are not necessarily quoted by Git, so an unquoted rename whose names
    contain `` b/`` is ambiguous; that returns ``None`` and the caller reads the
    ``rename from``/``rename to`` or ``---``/``+++`` lines instead. Equal pre- and
    post-image paths disambiguate ordinary edits, binary and mode-only changes.

    Args:
        body (str): The header with its ``diff --git `` prefix removed.

    Returns:
        tuple[str, str] | None: The decoded paths without ``a/``/``b/``, or
        ``None`` when the body is not a readable pair.

    Examples:
        >>> split_diff_git_paths("a/my file.txt b/my file.txt")
        ('my file.txt', 'my file.txt')
        >>> split_diff_git_paths('"a/caf\\\\303\\\\251.md" "b/caf\\\\303\\\\251.md"')
        ('café.md', 'café.md')
    """
    body = body.rstrip("\r\n")
    if body.startswith('"'):
        old, rest = _take_quoted_token(body)
        if old is None or not rest.startswith(" "):
            return None
        new = unquote_git_path(rest[1:])
        if new is None or not old.startswith(_A_PREFIX) or not new.startswith(_B_PREFIX):
            return None
        return old[len(_A_PREFIX) :], new[len(_B_PREFIX) :]
    if not body.startswith(_A_PREFIX):
        return None
    candidates: list[tuple[str, str]] = []
    for match in _HEADER_SEPARATOR_RE.finditer(body):
        old = body[len(_A_PREFIX) : match.start()]
        new = unquote_git_path(body[match.end() :])
        if old and new is not None and new.startswith(_B_PREFIX):
            candidates.append((old, new[len(_B_PREFIX) :]))
    same_path = [pair for pair in candidates if pair[0] == pair[1]]
    if len(same_path) == 1:
        return same_path[0]
    return candidates[0] if len(candidates) == 1 else None


__all__ = ["split_diff_git_paths", "unquote_git_path"]
