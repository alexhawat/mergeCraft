"""Inline review-comment anchor validation against the checked-out diff (#530, D8)."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Mapping

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_DIFF_FILE_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$")


@dataclass(frozen=True, slots=True)
class InlineAnchorIndex:
    """Valid single-line anchors and per-side hunk ranges from a unified diff."""

    anchors: frozenset[tuple[str, int, str]]
    hunk_ranges: dict[str, dict[str, list[tuple[int, int]]]]


@dataclass(frozen=True, slots=True)
class InlineAnchorAdjustment:
    """Outcome of validating one inline comment against the diff."""

    comment: dict[str, Any] | None
    demoted_body: str | None
    action: Literal["kept", "reanchored", "demoted"]


def build_inline_anchor_index(diff_text: str) -> InlineAnchorIndex:
    """Build the valid ``(path, line, side)`` anchor set from a unified diff."""
    anchors: set[tuple[str, int, str]] = set()
    hunk_ranges: dict[str, dict[str, list[tuple[int, int]]]] = defaultdict(
        lambda: {"LEFT": [], "RIGHT": []}
    )

    current_path: str | None = None
    old_line = 0
    new_line = 0

    for raw_line in diff_text.splitlines():
        file_match = _DIFF_FILE_RE.match(raw_line)
        if file_match:
            current_path = file_match.group(2)
            continue

        if current_path is None:
            continue

        hunk_match = _HUNK_RE.match(raw_line)
        if hunk_match:
            old_start = int(hunk_match.group(1))
            old_count = int(hunk_match.group(2) or "1")
            new_start = int(hunk_match.group(3))
            new_count = int(hunk_match.group(4) or "1")
            old_line = old_start
            new_line = new_start
            hunk_ranges[current_path]["LEFT"].append((old_start, old_start + max(old_count, 1) - 1))
            hunk_ranges[current_path]["RIGHT"].append(
                (new_start, new_start + max(new_count, 1) - 1)
            )
            continue

        if raw_line.startswith(("--- ", "+++ ")):
            continue

        prefix = raw_line[:1]
        if prefix == " ":
            anchors.add((current_path, old_line, "LEFT"))
            anchors.add((current_path, new_line, "RIGHT"))
            old_line += 1
            new_line += 1
        elif prefix == "+":
            anchors.add((current_path, new_line, "RIGHT"))
            new_line += 1
        elif prefix == "-":
            anchors.add((current_path, old_line, "LEFT"))
            old_line += 1

    return InlineAnchorIndex(
        anchors=frozenset(anchors),
        hunk_ranges={path: dict(sides) for path, sides in hunk_ranges.items()},
    )


def _nearest_line_in_hunks(
    path: str,
    *,
    side: str,
    requested_line: int,
    index: InlineAnchorIndex,
) -> int | None:
    valid = sorted(
        line
        for file_path, line, anchor_side in index.anchors
        if file_path == path and anchor_side == side
    )
    if not valid:
        return None
    ranges = index.hunk_ranges.get(path, {}).get(side) or []
    in_range = any(start <= requested_line <= end for start, end in ranges)
    if not in_range:
        return None
    return min(valid, key=lambda line: (abs(line - requested_line), line))


def _anchor_points(
    path: str,
    line: int | None,
    side: str,
    *,
    start_line: int | None = None,
    start_side: str | None = None,
) -> tuple[tuple[str, int, str], ...]:
    resolved_side = side or "RIGHT"
    if line is None:
        return ()
    if start_line is not None:
        resolved_start_side = start_side or resolved_side
        return (
            (path, int(start_line), resolved_start_side),
            (path, int(line), resolved_side),
        )
    return ((path, int(line), resolved_side),)


def format_demoted_inline_comment(comment: Mapping[str, Any]) -> str:
    path = str(comment.get("path") or "")
    line = comment.get("line")
    body = str(comment.get("body") or "").strip()
    anchor = f"{path}:{line}" if line is not None else path
    if body:
        return f"**`{anchor}`** (inline anchor unavailable)\n\n{body}"
    return f"**`{anchor}`** (inline anchor unavailable)"


def adjust_inline_comment_anchor(
    comment: Mapping[str, Any],
    *,
    index: InlineAnchorIndex,
) -> InlineAnchorAdjustment:
    """Keep, re-anchor, or demote one inline comment against ``index``."""
    path = str(comment.get("path") or "").strip()
    if not path:
        logger.warning("dropping inline comment — missing path")
        return InlineAnchorAdjustment(
            comment=None,
            demoted_body=format_demoted_inline_comment(comment),
            action="demoted",
        )

    line_raw = comment.get("line")
    line = int(line_raw) if line_raw is not None else None
    side = str(comment.get("side") or "RIGHT").upper()
    start_line_raw = comment.get("start_line")
    start_line = int(start_line_raw) if start_line_raw is not None else None
    start_side = str(comment.get("start_side")).upper() if comment.get("start_side") else None

    if path not in index.hunk_ranges:
        logger.warning("dropping inline comment on {}:{} — path not in diff", path, line)
        return InlineAnchorAdjustment(
            comment=None,
            demoted_body=format_demoted_inline_comment(comment),
            action="demoted",
        )

    if line is None:
        nearest = _nearest_line_in_hunks(path, side=side, requested_line=1, index=index)
        if nearest is None:
            logger.warning(
                "dropping inline comment on {} — no valid {} anchors in diff", path, side
            )
            return InlineAnchorAdjustment(
                comment=None,
                demoted_body=format_demoted_inline_comment(comment),
                action="demoted",
            )
        adjusted = dict(comment)
        adjusted["line"] = nearest
        adjusted.setdefault("side", side)
        logger.warning("re-anchoring inline comment on {}:None → {}:{}", path, path, nearest)
        return InlineAnchorAdjustment(comment=adjusted, demoted_body=None, action="reanchored")

    anchor_points = _anchor_points(
        path,
        line,
        side,
        start_line=start_line,
        start_side=start_side,
    )
    if anchor_points and all(point in index.anchors for point in anchor_points):
        return InlineAnchorAdjustment(comment=dict(comment), demoted_body=None, action="kept")

    nearest = _nearest_line_in_hunks(path, side=side, requested_line=line, index=index)
    if nearest is not None and (path, nearest, side) in index.anchors:
        adjusted = dict(comment)
        adjusted["line"] = nearest
        adjusted.setdefault("side", side)
        if start_line is not None:
            nearest_start = _nearest_line_in_hunks(
                path,
                side=start_side or side,
                requested_line=start_line,
                index=index,
            )
            if nearest_start is not None:
                adjusted["start_line"] = nearest_start
                adjusted["start_side"] = start_side or side
            else:
                adjusted.pop("start_line", None)
                adjusted.pop("start_side", None)
        logger.warning("re-anchoring inline comment on {}:{} → {}:{}", path, line, path, nearest)
        return InlineAnchorAdjustment(comment=adjusted, demoted_body=None, action="reanchored")

    logger.warning("dropping inline comment on {}:{} — path not in diff", path, line)
    return InlineAnchorAdjustment(
        comment=None,
        demoted_body=format_demoted_inline_comment(comment),
        action="demoted",
    )


def append_demoted_inline_comments(body: str, demoted_fragments: list[str]) -> str:
    """Append demoted inline comments into the review body."""
    if not demoted_fragments:
        return body
    snippets = "\n\n".join(fragment.strip() for fragment in demoted_fragments if fragment.strip())
    if not snippets:
        return body
    if body.rstrip():
        return f"{body.rstrip()}\n\n{snippets}\n"
    return f"{snippets}\n"


def _response_json(response: object) -> dict[str, Any] | None:
    json_method = getattr(response, "json", None)
    if not callable(json_method):
        return None
    try:
        payload = json_method()
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def parse_comment_422_index(response: object) -> int | None:
    """Return the failing inline-comment index from a GitHub 422 response, if present."""
    payload = _response_json(response)
    if payload is None:
        return None
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return None
    for error in errors:
        if not isinstance(error, dict):
            continue
        if error.get("field") != "comments":
            continue
        index = error.get("index")
        if isinstance(index, int):
            return index
    return None


def is_comments_anchor_422_response(response: object) -> bool:
    """Return whether a 422 response is about inline comment anchors."""
    if parse_comment_422_index(response) is not None:
        return True
    payload = _response_json(response)
    if payload is None:
        return False
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return False
    return any(isinstance(error, dict) and error.get("field") == "comments" for error in errors)


__all__ = [
    "InlineAnchorAdjustment",
    "InlineAnchorIndex",
    "adjust_inline_comment_anchor",
    "append_demoted_inline_comments",
    "build_inline_anchor_index",
    "format_demoted_inline_comment",
    "is_comments_anchor_422_response",
    "parse_comment_422_index",
]
