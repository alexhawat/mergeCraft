"""Shared finding-row normalization for eval scoring and convergence (RC6)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mergecraft.evals.scoring import BaselineIssue, ReportedFinding


def normalize_finding_path(value: str) -> str:
    """Strip leading ``./`` and ``a/`` / ``b/`` diff prefixes from a path."""
    text = value.strip().replace("\\", "/")
    for prefix in ("./", "a/", "b/"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text


def finding_line_bounds(row: Mapping[str, Any]) -> tuple[int, int]:
    """Return ``(start, end)`` from explicit lines or a ``line_range`` span."""
    span = row.get("line_range")
    if isinstance(span, (list, tuple)) and len(span) == 2:
        try:
            start, end = int(span[0]), int(span[1])
        except (TypeError, ValueError):  # fmt: skip
            start, end = 1, 1
    else:
        try:
            start = int(row.get("start_line") or row.get("line") or 1)
        except (TypeError, ValueError):  # fmt: skip
            start = 1
        try:
            end = int(row.get("end_line") or start)
        except (TypeError, ValueError):  # fmt: skip
            end = start
    if end < start:
        start, end = end, start
    return start, end


def finding_row_to_baseline(issue_id: str, row: Mapping[str, Any]) -> BaselineIssue:
    """Map a wire finding row to a :class:`BaselineIssue`."""
    from mergecraft.evals.scoring import BaselineIssue

    start, end = finding_line_bounds(row)
    return BaselineIssue(
        id=issue_id,
        path=normalize_finding_path(str(row.get("path") or "")),
        start_line=start,
        end_line=end,
        title=str(row.get("body") or row.get("message") or row.get("title") or ""),
    )


def finding_row_to_reported(row: Mapping[str, Any]) -> ReportedFinding:
    """Map a wire finding row to a :class:`ReportedFinding`."""
    from mergecraft.evals.scoring import ReportedFinding

    start, end = finding_line_bounds(row)
    return ReportedFinding(
        path=normalize_finding_path(str(row.get("path") or "")),
        start_line=start,
        end_line=end,
        message=str(row.get("body") or row.get("message") or row.get("title") or ""),
    )


def baseline_issues_overlap(first: BaselineIssue, second: BaselineIssue, *, slack: int) -> bool:
    """True when two baseline rows share a path and overlapping line spans."""
    if not first.path or first.path != second.path:
        return False
    return (
        second.start_line <= first.end_line + slack and first.start_line - slack <= second.end_line
    )


__all__ = [
    "baseline_issues_overlap",
    "finding_line_bounds",
    "finding_row_to_baseline",
    "finding_row_to_reported",
    "normalize_finding_path",
]
