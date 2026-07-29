"""Failure-to-hunk blame and unrelated-failure verdicts (K2 / K3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from mergecraft.ci.paths import extract_failure_paths, failure_line, primary_failure_path

BlameAttribution = Literal["caused_by_pr", "probably_not_this_pr", "unknown"]


@dataclass(frozen=True)
class BlameHunk:
    path: str
    line: int = 1


@dataclass(frozen=True)
class BlameVerdict:
    attribution: BlameAttribution
    summary: str
    hunk: BlameHunk | None = None
    base_branch_status: str | None = None


def _paths_overlap(failure_paths: list[str], pr_diff_paths: list[str]) -> list[str]:
    pr_set = set(pr_diff_paths)
    return [path for path in failure_paths if path in pr_set]


def blame_failure(
    *,
    failure: dict[str, Any],
    pr_diff_paths: list[str],
    base_branch_status: str | None,
) -> BlameVerdict:
    """Map a raw/normalized failure to a PR attribution verdict."""
    log_excerpt = str(failure.get("log_excerpt") or failure.get("log_text") or "")
    failure_paths = extract_failure_paths(log_excerpt)
    if not failure_paths:
        failure_paths = [primary_failure_path(log_excerpt)]

    overlap = _paths_overlap(failure_paths, pr_diff_paths)
    if overlap:
        path = overlap[0]
        return BlameVerdict(
            attribution="caused_by_pr",
            summary=f"Failure touches `{path}`, which this PR modifies.",
            hunk=BlameHunk(path=path, line=failure_line(log_excerpt, path=path)),
            base_branch_status=base_branch_status,
        )

    primary = failure_paths[0]
    if base_branch_status:
        return BlameVerdict(
            attribution="probably_not_this_pr",
            summary=(
                f"Failure in `{primary}` is probably not this PR — "
                f"base branch status for the same fingerprint is {base_branch_status}."
            ),
            hunk=BlameHunk(path=primary, line=failure_line(log_excerpt, path=primary)),
            base_branch_status=base_branch_status,
        )

    return BlameVerdict(
        attribution="probably_not_this_pr",
        summary=(
            f"Failure in `{primary}` does not overlap the PR diff; "
            "causation is unknown — probably not this PR."
        ),
        hunk=BlameHunk(path=primary, line=failure_line(log_excerpt, path=primary)),
        base_branch_status=None,
    )


__all__ = ["BlameAttribution", "BlameHunk", "BlameVerdict", "blame_failure"]
