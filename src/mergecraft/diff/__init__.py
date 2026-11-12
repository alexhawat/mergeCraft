"""Shared unified-diff parsing: one reader for the paths a ``git diff`` touches.

Exports:
    DiffFile: One ``diff --git`` section and the paths it names.
    DiffStatus: ``added``, ``deleted``, ``modified``, ``renamed`` or ``copied``.
    ParsedDiff: The text before the first section plus every section.
    parse_diff: Parse a unified diff into a :class:`ParsedDiff`.
    changed_paths_in_diff: The post-image path of every section, in first-seen order.
    diff_lines: Split diff text on ``\\n`` only, as Git does.
    unquote_git_path: Decode one possibly C-quoted Git path token.
    split_diff_git_paths: Split a ``diff --git`` header body into its two paths.
"""

from __future__ import annotations

from mergecraft.diff.quoting import split_diff_git_paths, unquote_git_path
from mergecraft.diff.sections import (
    DiffFile,
    DiffStatus,
    ParsedDiff,
    changed_paths_in_diff,
    diff_lines,
    parse_diff,
)

__all__ = [
    "DiffFile",
    "DiffStatus",
    "ParsedDiff",
    "changed_paths_in_diff",
    "diff_lines",
    "parse_diff",
    "split_diff_git_paths",
    "unquote_git_path",
]
