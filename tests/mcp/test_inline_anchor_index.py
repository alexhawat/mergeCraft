"""Inline-anchor index: hunk content lines that look like file headers (#1556).

A line inside a hunk is content, whatever it looks like. A removed SQL/Lua
comment ``-- old comment`` renders as ``--- old comment`` and an added line
whose text starts with ``++ `` renders as ``+++ …``. ``build_inline_anchor_index``
must treat ``--- `` / ``+++ `` as headers only before a file's first hunk, and
must stop treating a hunk as open once its declared old and new counts are
consumed, so a header that follows a completed hunk (a plain ``diff -u``
concatenation) is still a header.
"""

from __future__ import annotations

import pytest

from mergecraft.mcp.inline_anchors import (
    adjust_inline_comment_anchor,
    build_inline_anchor_index,
)

#: Added content line ``++ x`` renders as ``+++ x`` inside the hunk tail.
_ADDED_PLUS_PLUS = (
    "diff --git a/m.sql b/m.sql\n"
    "index 1..2 100644\n"
    "--- a/m.sql\n"
    "+++ b/m.sql\n"
    "@@ -1,3 +1,4 @@\n"
    " a\n"
    " b\n"
    " c\n"
    "+++ x\n"
)

#: Removed SQL comment ``-- old comment`` renders as ``--- old comment``.
_REMOVED_SQL_COMMENT = (
    "diff --git a/m.sql b/m.sql\n"
    "index 1..2 100644\n"
    "--- a/m.sql\n"
    "+++ b/m.sql\n"
    "@@ -1,4 +1,3 @@\n"
    " a\n"
    "--- old comment\n"
    " b\n"
    " c\n"
)

#: A removed comment in the middle: every later anchor must keep its true line.
_REMOVED_SQL_COMMENT_MIDDLE = (
    "diff --git a/m.sql b/m.sql\n"
    "--- a/m.sql\n"
    "+++ b/m.sql\n"
    "@@ -1,5 +1,4 @@\n"
    " a\n"
    "--- old comment\n"
    " b\n"
    " c\n"
    " d\n"
)

#: A normal file whose header pair precedes its only hunk.
_SIMPLE = "diff --git a/m.sql b/m.sql\n--- a/m.sql\n+++ b/m.sql\n@@ -1,2 +1,2 @@\n a\n-b\n+c\n"

#: Two files in one diff: the second file's header pair must reset the state.
_TWO_FILES = (
    "diff --git a/one.txt b/one.txt\n"
    "--- a/one.txt\n"
    "+++ b/one.txt\n"
    "@@ -1,2 +1,2 @@\n"
    " a\n"
    "-b\n"
    "+c\n"
    "diff --git a/two.txt b/two.txt\n"
    "--- a/two.txt\n"
    "+++ b/two.txt\n"
    "@@ -1,2 +1,2 @@\n"
    " x\n"
    "-y\n"
    "+z\n"
)

#: A completed hunk followed by another file's header without a ``diff --git``.
_CONCATENATED = (
    "diff --git a/one.txt b/one.txt\n"
    "--- a/one.txt\n"
    "+++ b/one.txt\n"
    "@@ -1,2 +1,2 @@\n"
    " a\n"
    "-b\n"
    "+c\n"
    "--- a/two.txt\n"
    "+++ b/two.txt\n"
    "@@ -1,2 +1,2 @@\n"
    " x\n"
    "-y\n"
    "+z\n"
)


def _lines(diff_text: str, side: str) -> list[int]:
    """Return the sorted anchor line numbers for one side of ``diff_text``."""
    index = build_inline_anchor_index(diff_text)
    return sorted(line for _path, line, anchor_side in index.anchors if anchor_side == side)


def test_added_line_starting_with_two_pluses_is_anchored() -> None:
    """``++ x`` adds ``+++ x`` to the hunk; the last RIGHT anchor is line 4."""
    index = build_inline_anchor_index(_ADDED_PLUS_PLUS)

    assert _lines(_ADDED_PLUS_PLUS, "RIGHT") == [1, 2, 3, 4]
    assert index.hunk_ranges["m.sql"]["RIGHT"] == [(1, 4)]


def test_removed_sql_comment_line_is_anchored() -> None:
    """A removed ``-- old comment`` keeps its LEFT anchor at the true line."""
    index = build_inline_anchor_index(_REMOVED_SQL_COMMENT)

    assert _lines(_REMOVED_SQL_COMMENT, "LEFT") == [1, 2, 3, 4]
    assert index.hunk_ranges["m.sql"]["LEFT"] == [(1, 4)]


@pytest.mark.parametrize(
    ("diff_text", "side"),
    [
        pytest.param(_ADDED_PLUS_PLUS, "RIGHT", id="added-line"),
        pytest.param(_REMOVED_SQL_COMMENT, "LEFT", id="removed-line"),
    ],
)
def test_comment_on_last_line_of_such_a_hunk_is_kept(diff_text: str, side: str) -> None:
    """A correctly placed comment on line 4 is not moved one line up."""
    index = build_inline_anchor_index(diff_text)

    adjusted = adjust_inline_comment_anchor(
        {"path": "m.sql", "line": 4, "side": side, "body": "b"},
        index=index,
    )

    assert adjusted.action == "kept"
    assert adjusted.comment is not None
    assert adjusted.comment["line"] == 4


def test_lines_after_the_content_line_keep_their_numbers() -> None:
    """Skipping the content line under-counts every later anchor by one."""
    assert _lines(_REMOVED_SQL_COMMENT_MIDDLE, "LEFT") == [1, 2, 3, 4, 5]
    assert _lines(_REMOVED_SQL_COMMENT_MIDDLE, "RIGHT") == [1, 2, 3, 4]


def test_file_headers_before_the_first_hunk_are_not_anchors() -> None:
    """The ``---``/``+++`` pair before a hunk is a header, not content."""
    index = build_inline_anchor_index(_SIMPLE)

    assert index.anchors == frozenset(
        {
            ("m.sql", 1, "LEFT"),
            ("m.sql", 1, "RIGHT"),
            ("m.sql", 2, "LEFT"),
            ("m.sql", 2, "RIGHT"),
        }
    )


def test_second_file_headers_reset_the_state() -> None:
    """The second file's header pair is a header, not content of the first file."""
    index = build_inline_anchor_index(_TWO_FILES)

    assert index.anchors == frozenset(
        {
            ("one.txt", 1, "LEFT"),
            ("one.txt", 1, "RIGHT"),
            ("one.txt", 2, "LEFT"),
            ("one.txt", 2, "RIGHT"),
            ("two.txt", 1, "LEFT"),
            ("two.txt", 1, "RIGHT"),
            ("two.txt", 2, "LEFT"),
            ("two.txt", 2, "RIGHT"),
        }
    )


def test_header_after_a_completed_hunk_is_not_anchored_as_content() -> None:
    """A header pair after a fully consumed hunk is not removed/added content.

    A concatenated section without its own ``diff --git`` line keeps the previous
    section's path (out of scope); the contract here is only the header rule: a
    header line must not consume a hunk line or become an anchor.
    """
    index = build_inline_anchor_index(_CONCATENATED)

    assert ("one.txt", 3, "LEFT") not in index.anchors
    assert ("one.txt", 3, "RIGHT") not in index.anchors
    assert all(path == "one.txt" for path, _line, _side in index.anchors)
