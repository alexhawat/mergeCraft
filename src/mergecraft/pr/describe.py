"""Standalone describe output — text-only PR summary (DG8, convention 3).

Library surface only — not wired into ``select_mode`` / dispatch yet (DG7/DG8 pairing).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from pathlib import Path

from mergecraft.analyzers.scope import changed_paths_from_scope, parse_diff_scope
from mergecraft.modes._pr_summary_format import PR_SUMMARY_FORMAT


class DescribeOutput(BaseModel):
    """Prose sections returned by ``/mergecraft describe`` — never persisted."""

    model_config = ConfigDict(extra="forbid")

    title: str
    body: str
    walkthrough: str
    risk_summary: str
    test_summary: str


def _metadata_str(pr_metadata: dict[str, object], key: str, default: str = "") -> str:
    value = pr_metadata.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else default


def build_describe_output(
    *,
    diff: str,
    pr_metadata: dict[str, object],
    repo_root: Path | None = None,
) -> DescribeOutput:
    """Build standalone describe prose from a diff and PR metadata.

    Output-only: ``repo_root`` is accepted for call-site symmetry but is never
    written to. Describe guidance follows :data:`PR_SUMMARY_FORMAT` shape without
    posting a review.
    """
    _ = repo_root  # convention 3 — inspect-only; never mutate the reviewed tree

    title = _metadata_str(pr_metadata, "title", "Describe this pull request")
    pr_body = _metadata_str(pr_metadata, "body")
    pr_number = pr_metadata.get("number")
    number_text = f"#{pr_number}" if isinstance(pr_number, int) else "this PR"

    scope = parse_diff_scope(diff)
    paths = changed_paths_from_scope(scope)
    file_count = len(paths) or len(scope.hunk_ranges)

    body = (
        f"**{title}** ({number_text}) summarizes {file_count} changed file"
        f"{'' if file_count == 1 else 's'}."
    )
    if pr_body:
        body = f"{body}\n\nAuthor intent: {pr_body}"
    body = (
        f"{body}\n\nDescribe output follows mergeCraft's review summary discipline "
        f"(see PR summary format — {len(PR_SUMMARY_FORMAT)} chars of guidance)."
    )

    walkthrough_lines = [
        f"- `{path}` — inspect added/changed hunks in the unified diff." for path in paths[:8]
    ]
    if not walkthrough_lines:
        walkthrough_lines = ["- No file paths parsed from the diff; re-run after checkout."]
    walkthrough = (
        "**Walkthrough**\n\n"
        "Read the diff top-to-bottom and note each substantive hunk:\n\n"
        + "\n".join(walkthrough_lines)
    )

    risky_paths = [
        path for path in paths if any(part in path.lower() for part in ("auth", "security"))
    ]
    risk_summary = "**Risk summary**\n\n" + (
        f"Touches sensitive paths ({', '.join(f'`{p}`' for p in risky_paths)}). "
        "Verify authz, secret handling, and rollback before merge."
        if risky_paths
        else "No high-stakes path prefixes detected; still validate behavior against intent."
    )

    test_summary = (
        "**Test summary**\n\n"
        "Exercise the changed code paths with unit or integration tests covering "
        "the new branches introduced in the diff. Add regression tests when the "
        "change fixes a bug or alters security-sensitive behavior."
    )

    return DescribeOutput(
        title=title,
        body=body,
        walkthrough=walkthrough,
        risk_summary=risk_summary,
        test_summary=test_summary,
    )


__all__ = ["DescribeOutput", "build_describe_output"]
