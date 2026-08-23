"""Incremental first-pass miss labelling (RC9, D10)."""

from __future__ import annotations

from mergecraft.analyzers.scope import (
    iter_added_diff_lines,
    line_intersects_hunks,
    parse_diff_scope,
)

FIRST_PASS_MISS_LABEL = (
    "_(First-pass miss — this line was already present at the first reviewed commit.)_"
)


def is_first_pass_miss_line(path: str, line: int, incremental_diff_text: str) -> bool:
    """Return True when ``line`` on ``path`` was not added by the incremental diff."""
    added = {
        (file_path, line_no)
        for file_path, line_no, _ in iter_added_diff_lines(incremental_diff_text)
    }
    if (path, line) in added:
        return False
    scope = parse_diff_scope(incremental_diff_text)
    return line_intersects_hunks(path, line, line, scope)


def apply_first_pass_miss_label(
    body: str,
    *,
    path: str | None = None,
    line: int | None = None,
    incremental_diff_text: str | None = None,
) -> str:
    """Prefix ``body`` with the D10 label when the anchor is a first-pass miss."""
    if (
        path is not None
        and line is not None
        and incremental_diff_text is not None
        and not is_first_pass_miss_line(path, line, incremental_diff_text)
    ):
        return body
    if body.startswith(FIRST_PASS_MISS_LABEL):
        return body
    return f"{FIRST_PASS_MISS_LABEL}\n\n{body}"


__all__ = [
    "FIRST_PASS_MISS_LABEL",
    "apply_first_pass_miss_label",
    "is_first_pass_miss_line",
]
