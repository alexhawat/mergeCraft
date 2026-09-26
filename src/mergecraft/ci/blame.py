"""Failure-to-hunk blame and unrelated-failure verdicts (K2 / K3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from mergecraft.ci.paths import (
    extract_failure_paths,
    failure_line,
    normalize_repo_path,
)

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
    pr_set = {normalize_repo_path(path) for path in pr_diff_paths}
    return [path for path in failure_paths if path in pr_set]


def _normalized_base_status(base_branch_status: str | None) -> str:
    """Return the base conclusion lowercased, or ``""`` when absent (BL-D3)."""
    return (base_branch_status or "").strip().lower()


def _base_failure_summary(*, primary: str | None) -> str:
    if primary is not None:
        return (
            "Base branch concluded `failure` for this fingerprint (the failure is in "
            f"`{primary}`); the failure is pre-existing and not introduced by this PR."
        )
    return (
        "Base branch concluded `failure` for this fingerprint; the failure is "
        "pre-existing and not introduced by this PR."
    )


def _unattributed_summary(*, primary: str | None, base_status: str, summary_status: str) -> str:
    """Build an ``unknown`` summary naming the evidence and what would clear it (BL-D7)."""
    where = (
        f"the failure in `{primary}` does not overlap the PR diff"
        if primary is not None
        else "the log carries no failure path"
    )
    if summary_status == "success":
        return (
            f"Base branch passed with this fingerprint and {where}; the failure is new here "
            "and unattributed — it blocks until a base-branch failure or a retry flip clears it."
        )
    if summary_status:
        return (
            f"Base branch concluded `{base_status}` for this fingerprint and {where}; the "
            "failure is unattributed — it blocks until a base-branch failure or a retry flip "
            "clears it."
        )
    return (
        f"No base-branch evidence and {where}; the failure is unattributed — it blocks until "
        "a base-branch failure or a retry flip clears it."
    )


def blame_failure(
    *,
    failure: dict[str, Any],
    pr_diff_paths: list[str],
    base_branch_status: str | None,
) -> BlameVerdict:
    """Map a raw/normalized failure to a PR attribution verdict.

    Three outcomes, all reachable:

    * ``caused_by_pr`` — a failure path overlaps the (normalised) PR diff.
    * ``probably_not_this_pr`` — a same-fingerprint base run concluded ``failure``;
      the only positive exoneration signal.
    * ``unknown`` — the evidence does not decide: no overlap and no base failure,
      or no failure path extracted at all.
    """
    log_excerpt = str(failure.get("log_excerpt") or failure.get("log_text") or "")
    stored_paths = failure.get("failure_paths")
    if isinstance(stored_paths, list) and stored_paths:
        failure_paths = [normalize_repo_path(str(path)) for path in stored_paths]
    else:
        failure_paths = extract_failure_paths(log_excerpt)
    primary = failure_paths[0] if failure_paths else None

    overlap = _paths_overlap(failure_paths, pr_diff_paths)
    if overlap:
        path = overlap[0]
        return BlameVerdict(
            attribution="caused_by_pr",
            summary=f"Failure touches `{path}`, which this PR modifies.",
            hunk=BlameHunk(path=path, line=failure_line(log_excerpt, path=path)),
            base_branch_status=base_branch_status,
        )

    normalized_status = _normalized_base_status(base_branch_status)
    if normalized_status == "failure":
        return BlameVerdict(
            attribution="probably_not_this_pr",
            summary=_base_failure_summary(primary=primary),
            hunk=None,
            base_branch_status=base_branch_status,
        )

    # No overlap and no base failure: the evidence does not decide (BL-D1).
    return BlameVerdict(
        attribution="unknown",
        summary=_unattributed_summary(
            primary=primary,
            base_status=(base_branch_status or "").strip(),
            summary_status=normalized_status,
        ),
        hunk=None,
        base_branch_status=base_branch_status,
    )


__all__ = ["BlameAttribution", "BlameHunk", "BlameVerdict", "blame_failure"]
