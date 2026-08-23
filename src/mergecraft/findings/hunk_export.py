"""Pure Hunk comment exporter for ``--output-format hunk`` (issue #451, D3).

Maps normalized findings to the stdin JSON envelope Hunk expects
(``{"comments":[...]}``) without subprocess, HTTP, or a Hunk dependency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from mergecraft.analyzers.scope import parse_diff_scope

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from mergecraft.analyzers.finding import Finding

HUNK_COMMENT_AUTHOR = "mergeCraft"

FileFindingsMode = Literal["drop", "first-changed-line"]
_VALID_FILE_FINDINGS: frozenset[str] = frozenset({"drop", "first-changed-line"})


def count_dropped_file_level_findings(findings: Sequence[Finding]) -> int:
    """Return how many findings lack a line anchor (``start_line is None``)."""
    return sum(1 for finding in findings if finding.start_line is None)


def format_file_level_drop_warning(count: int) -> str:
    """Human stderr copy when file-level findings are omitted from export."""
    noun = "finding" if count == 1 else "findings"
    return f"{count} file-level {noun} not exportable"


def first_changed_lines_from_diff(diff_text: str) -> dict[str, int]:
    """Map each changed path to the first new-file line number in ``diff_text``."""
    scope = parse_diff_scope(diff_text)
    return {
        path: min(start for start, _ in ranges)
        for path, ranges in scope.hunk_ranges.items()
        if ranges
    }


def _format_hunk_summary(finding: Finding, *, file_level: bool = False) -> str:
    prefix = "[file-level] " if file_level else ""
    return f"{prefix}{finding.rule_id} [{finding.severity}/{finding.confidence}]"


def _format_hunk_rationale(finding: Finding) -> str:
    parts: list[str] = [finding.message]
    if finding.remediation:
        parts.append(finding.remediation)
    parts.extend(finding.evidence)
    return "\n\n".join(parts)


def export_hunk_comments(
    findings: Sequence[Finding],
    *,
    file_findings: str = "drop",
    first_changed_lines: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Convert findings to the Hunk ``comment apply --stdin`` payload."""
    if file_findings not in _VALID_FILE_FINDINGS:
        msg = (
            f"file_findings must be one of {sorted(_VALID_FILE_FINDINGS)!r}, got {file_findings!r}"
        )
        raise ValueError(msg)

    comments: list[dict[str, Any]] = []
    for finding in findings:
        if finding.start_line is None:
            if file_findings == "drop":
                continue
            if first_changed_lines is None:
                continue
            new_line = first_changed_lines.get(finding.path)
            if new_line is None:
                continue
            comments.append(
                {
                    "filePath": finding.path,
                    "newLine": new_line,
                    "summary": _format_hunk_summary(finding, file_level=True),
                    "rationale": _format_hunk_rationale(finding),
                    "author": HUNK_COMMENT_AUTHOR,
                }
            )
            continue

        comments.append(
            {
                "filePath": finding.path,
                "newLine": finding.start_line,
                "summary": _format_hunk_summary(finding),
                "rationale": _format_hunk_rationale(finding),
                "author": HUNK_COMMENT_AUTHOR,
            }
        )

    return {"comments": comments}


__all__ = [
    "HUNK_COMMENT_AUTHOR",
    "count_dropped_file_level_findings",
    "export_hunk_comments",
    "first_changed_lines_from_diff",
    "format_file_level_drop_warning",
]
