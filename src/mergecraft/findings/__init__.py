"""Finding carryover — what a review raised that a merge would otherwise bury.

A merged pull request keeps its inline review comments forever, but nobody
re-opens a merged PR. Findings mergeCraft raised and the author neither fixed
nor rebutted are therefore lost to attention, not to storage. This package
turns those threads back into work: it reads them, decides which ones survive,
and renders each into an issue keyed by the finding fingerprint the reviewer
already stamps.

Exports:
    CarryoverFinding: One surviving inline finding, ready to file.
    ReviewThreadPage: A pull request's review threads plus truncation state.
    carryover_findings: Pure selection over fetched threads.
    fetch_review_threads: Read a pull request's review threads.
    issue_body: Render the issue body for one finding.
    issue_title: Render the issue title for one finding.
"""

from __future__ import annotations

from mergecraft.findings.select import (
    CarryoverFinding,
    carryover_findings,
    issue_body,
    issue_title,
)
from mergecraft.findings.threads import ReviewThreadPage, fetch_review_threads

__all__ = [
    "CarryoverFinding",
    "ReviewThreadPage",
    "carryover_findings",
    "fetch_review_threads",
    "issue_body",
    "issue_title",
]
