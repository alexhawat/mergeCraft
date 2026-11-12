"""Split a ``git diff`` into per-file sections and name each section's paths.

One reader for the question "which files does this diff touch, and how", so
review scope, ignore-path filtering, confinement, incremental re-review and
analyzer targeting all agree on the answer. It handles:

- quoted paths (non-ASCII, quotes, control characters), decoded to UTF-8;
- unquoted paths with spaces, including the ambiguous `` b/`` case, resolved
  from the ``rename``/``copy``/``---``/``+++`` lines;
- renames and copies (both images named), additions and deletions
  (``/dev/null`` on one side), binary entries and mode-only entries.

Only lines before a section's first ``@@`` are read as headers: inside a hunk an
added line that begins ``++ `` renders as ``+++ `` and is content, not a header.

Exports:
    DiffFile: One ``diff --git`` section and the paths it names.
    ParsedDiff: The text before the first section plus every section.
    parse_diff: Parse a unified diff into a :class:`ParsedDiff`.
    changed_paths_in_diff: The post-image path of every section, in first-seen order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from mergecraft.diff.quoting import split_diff_git_paths, unquote_git_path

DiffStatus = Literal["added", "deleted", "modified", "renamed", "copied"]

_HEADER = "diff --git "
_DEV_NULL = "/dev/null"
_A_PREFIX = "a/"
_B_PREFIX = "b/"
# (line prefix, image it names, diff prefix to strip)
_IMAGE_LINES: tuple[tuple[str, str, str], ...] = (
    ("rename from ", "old", ""),
    ("rename to ", "new", ""),
    ("copy from ", "old", ""),
    ("copy to ", "new", ""),
    ("--- ", "old", _A_PREFIX),
    ("+++ ", "new", _B_PREFIX),
)


@dataclass(frozen=True, slots=True)
class DiffFile:
    """One ``diff --git`` section of a unified diff.

    Attributes:
        old_path (str | None): Repository-relative pre-image path; ``None`` for
            an added file or an unreadable header.
        new_path (str | None): Repository-relative post-image path; ``None`` for
            a deleted file or an unreadable header.
        status (DiffStatus): ``added``, ``deleted``, ``modified``, ``renamed``
            or ``copied``. A mode-only or binary change is ``modified``.
        binary (bool): The section carries a binary patch or a ``Binary files``
            marker instead of text hunks.
        text (str): The raw section, header line included, line endings kept.
    """

    old_path: str | None
    new_path: str | None
    status: DiffStatus
    binary: bool
    text: str

    @property
    def path(self) -> str | None:
        """The post-image path, or the removed path for a deletion."""
        return self.new_path if self.new_path is not None else self.old_path

    @property
    def paths(self) -> tuple[str, ...]:
        """``(path, pre-image)`` without duplicates; one entry unless renamed or copied."""
        return tuple(dict.fromkeys(p for p in (self.path, self.old_path) if p is not None))


@dataclass(frozen=True, slots=True)
class ParsedDiff:
    """A unified diff split into its preamble and per-file sections.

    Attributes:
        preamble (str): Text before the first ``diff --git`` line (often empty).
        files (tuple[DiffFile, ...]): The sections in diff order.
    """

    preamble: str
    files: tuple[DiffFile, ...]


def _image_path(token: str, diff_prefix: str) -> str | None:
    """Decode one ``rename``/``copy``/``---``/``+++`` path token."""
    if diff_prefix:
        # Git separates a space-bearing ---/+++ path from an optional trailing
        # tab (or timestamp) with a tab; a tab inside a name is always quoted.
        token = token.split("\t", 1)[0]
    if token == _DEV_NULL:
        return _DEV_NULL
    decoded = unquote_git_path(token)
    if decoded is None:
        return None
    return decoded.removeprefix(diff_prefix) if diff_prefix else decoded


def _build_section(lines: list[str]) -> DiffFile:
    header = lines[0].rstrip("\r\n")
    pair = split_diff_git_paths(header[len(_HEADER) :])
    images: dict[str, str] = {}
    added = deleted = binary = False
    status: DiffStatus = "modified"
    for raw in lines[1:]:
        line = raw.rstrip("\r\n")
        if line.startswith("@@"):
            break
        if line.startswith("new file mode"):
            added = True
        elif line.startswith("deleted file mode"):
            deleted = True
        elif line.startswith("rename from "):
            status = "renamed"
        elif line.startswith("copy from "):
            status = "copied"
        elif line.startswith(("Binary files ", "GIT binary patch")):
            binary = True
        for prefix, image, diff_prefix in _IMAGE_LINES:
            if line.startswith(prefix):
                decoded = _image_path(line[len(prefix) :], diff_prefix)
                if decoded is not None:
                    images.setdefault(image, decoded)
                break
    # Extended header lines are authoritative: they are unambiguous where an
    # unquoted header body containing " b/" is not.
    old: str | None = images.get("old", pair[0] if pair is not None else None)
    new: str | None = images.get("new", pair[1] if pair is not None else None)
    if old == _DEV_NULL:
        added, old = True, None
    if new == _DEV_NULL:
        deleted, new = True, None
    if added:
        status, old = "added", None
    elif deleted:
        status, new = "deleted", None
    return DiffFile(
        old_path=old,
        new_path=new,
        status=status,
        binary=binary,
        text="".join(lines),
    )


def parse_diff(diff_text: str) -> ParsedDiff:
    """Split ``diff_text`` into its preamble and one :class:`DiffFile` per section.

    A section whose paths cannot be read is still returned (with ``None`` paths)
    so a caller can decide whether an unreadable entry is kept or dropped.

    Args:
        diff_text (str): A unified diff as ``git diff`` renders it.

    Returns:
        ParsedDiff: The preamble and sections, in diff order. Concatenating
        ``preamble`` and every section's ``text`` reproduces ``diff_text``.

    Examples:
        >>> parsed = parse_diff('diff --git a/x.py b/y.py\\nrename from x.py\\nrename to y.py\\n')
        >>> [(f.old_path, f.new_path, f.status) for f in parsed.files]
        [('x.py', 'y.py', 'renamed')]
    """
    preamble: list[str] = []
    sections: list[list[str]] = []
    for line in str(diff_text).splitlines(keepends=True):
        if line.startswith(_HEADER):
            sections.append([line])
        elif sections:
            sections[-1].append(line)
        else:
            preamble.append(line)
    return ParsedDiff(
        preamble="".join(preamble),
        files=tuple(_build_section(lines) for lines in sections),
    )


def changed_paths_in_diff(diff_text: str, *, include_deleted: bool = True) -> list[str]:
    """Return the post-image path of every section, in first-seen order.

    A deleted file is named by the path it was removed from, unless
    ``include_deleted`` is false (a caller handing paths to a tool that reads
    them from disk). Rename pre-images are not included; use :func:`parse_diff`
    and :attr:`DiffFile.paths` for those.

    Args:
        diff_text (str): A unified diff as ``git diff`` renders it.
        include_deleted (bool): Whether deleted files are listed.

    Returns:
        list[str]: Repository-relative, decoded paths without duplicates.

    Examples:
        >>> changed_paths_in_diff('diff --git "a/caf\\\\303\\\\251.md" "b/caf\\\\303\\\\251.md"\\n')
        ['café.md']
    """
    seen: dict[str, None] = {}
    for section in parse_diff(diff_text).files:
        if not include_deleted and section.status == "deleted":
            continue
        if section.path is not None:
            seen.setdefault(section.path, None)
    return list(seen)


__all__ = ["DiffFile", "DiffStatus", "ParsedDiff", "changed_paths_in_diff", "parse_diff"]
