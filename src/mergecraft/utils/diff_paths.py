"""Diff path extraction shared by evidence assembly and verifier confinement."""

from __future__ import annotations

import re

from mergecraft.analyzers.scope import parse_diff_scope

_HEADER = "diff --git "
# One header entry: ``a/<old> b/<new>``, where either side may instead be a
# C-quoted path (``"a/…"``) as git writes it when a path has a space, a quote or
# a non-ASCII byte under the default ``core.quotePath``.
_HEADER_RE = re.compile(
    r"^diff --git (?:a/(?P<old>\S+)|"
    r'"(?P<old_quoted>(?:\\.|[^"\\])*)")'
    r" (?:b/(?P<new>\S+)|"
    r'"(?P<new_quoted>(?:\\.|[^"\\])*)")$'
)
# Git's C-style escapes inside a quoted path.
_QUOTED_ESCAPES = {
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
    '"': '"',
}
_OCTAL_DIGITS = frozenset("01234567")


def _unescape_quoted_path(raw: str) -> str:
    """Decode the body of one git-quoted path (the text between the quotes).

    Git's quoted form is byte-oriented: a non-ASCII byte arrives as one octal
    escape, so the escapes are re-assembled as bytes and decoded as UTF-8 once —
    ``\\303\\251`` is ``é``, not two characters.
    """
    data = bytearray()
    index = 0
    while index < len(raw):
        char = raw[index]
        if char != "\\" or index + 1 >= len(raw):
            data.extend(char.encode("utf-8", errors="surrogatepass"))
            index += 1
            continue
        nxt = raw[index + 1]
        if nxt in _QUOTED_ESCAPES:
            data.extend(_QUOTED_ESCAPES[nxt].encode("utf-8"))
            index += 2
            continue
        octal = raw[index + 1 : index + 4]
        if len(octal) == 3 and _OCTAL_DIGITS.issuperset(octal):
            data.append(int(octal, 8))
            index += 4
            continue
        data.extend(nxt.encode("utf-8", errors="surrogatepass"))
        index += 2
    return data.decode("utf-8", errors="surrogateescape")


def _quoted_or_plain(match: re.Match[str], *, plain: str, quoted: str, prefix: str) -> str:
    """Return one side of a header pair without its quotes or ``a/``/``b/`` prefix."""
    value = match.group(plain)
    if value is not None:
        return str(value)
    decoded = _unescape_quoted_path(match.group(quoted) or "")
    return decoded[len(prefix) :] if decoded.startswith(prefix) else decoded


def paths_from_diff_headers(diff_text: str) -> set[str]:
    """Return every path a ``diff --git`` header names, pre-image and post-image.

    Hunks say what changed line by line; a header says which files an entry is
    about. Using both matters because a review judges *paths*: a pure rename, a
    binary-only entry and a mode-only entry all touch a file without
    contributing a hunk, so a hunk-only reading of the diff would leave them out
    of the change set entirely.

    Both images of a rename are returned — the old path stopped existing and the
    new one started, so a rule scoped over either has been touched. Quoted paths
    are decoded, and the ``a/``/``b/`` prefix is stripped, so a caller compares
    repository-relative paths.

    Args:
        diff_text (str): A unified diff as git renders it.

    Returns:
        set[str]: The paths named by the diff's headers, without duplicates.

    Examples:
        >>> sorted(paths_from_diff_headers("diff --git a/x.py b/y.py\\n"))
        ['x.py', 'y.py']
    """
    found: set[str] = set()
    for line in diff_text.splitlines():
        if not line.startswith(_HEADER):
            continue
        match = _HEADER_RE.match(line)
        if match is None:
            continue
        old = _quoted_or_plain(match, plain="old", quoted="old_quoted", prefix="a/")
        new = _quoted_or_plain(match, plain="new", quoted="new_quoted", prefix="b/")
        found.update(path for path in (old, new) if path)
    return found


def changed_paths_from_diff(diff_text: str) -> list[str]:
    """Return every path the diff touches, sorted and deduplicated.

    Three signals are unioned, and each catches something the others miss:

    - ``analyzers/scope.py``'s hunk ranges, added files and scope exceptions
      (changed workflows, migrations, lockfiles, dependency manifests). Those are
      precisely the paths that drive blast radius, so this reuses that signal
      rather than writing a second diff parser with its own idea of what a
      migration looks like.
    - The ``diff --git`` headers, which are the only place a pure rename, a
      binary-only entry or a mode-only entry appears — none of them has a hunk
      for the scope parser to read.

    Unioning the exception sets in matters: a lockfile or workflow changed with
    no surviving hunk range would otherwise drop out of the path list and
    silently soften the classification.
    """
    if not diff_text.strip():
        return []
    scope = parse_diff_scope(diff_text)
    paths: set[str] = set(scope.hunk_ranges)
    paths |= set(scope.added_files)
    paths |= set(scope.changed_lockfiles)
    paths |= set(scope.changed_workflows)
    paths |= set(scope.changed_migrations)
    paths |= set(scope.changed_dependency_manifests)
    paths |= paths_from_diff_headers(diff_text)
    return sorted(paths)


__all__ = ["changed_paths_from_diff", "paths_from_diff_headers"]
