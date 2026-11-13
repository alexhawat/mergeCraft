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

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mergecraft.findings.select import (
        CarryoverFinding,
        carryover_findings,
        issue_body,
        issue_title,
    )
    from mergecraft.findings.threads import ReviewThreadPage, fetch_review_threads

_EXPORT_MODULES = {
    "CarryoverFinding": "mergecraft.findings.select",
    "carryover_findings": "mergecraft.findings.select",
    "issue_body": "mergecraft.findings.select",
    "issue_title": "mergecraft.findings.select",
    "ReviewThreadPage": "mergecraft.findings.threads",
    "fetch_review_threads": "mergecraft.findings.threads",
}

__all__ = [
    "CarryoverFinding",
    "ReviewThreadPage",
    "carryover_findings",
    "fetch_review_threads",
    "issue_body",
    "issue_title",
]


def __getattr__(name: str) -> Any:
    """Resolve public re-exports without loading unrelated runtime subsystems."""
    if name not in _EXPORT_MODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(_EXPORT_MODULES[name]), name)
    globals()[name] = value
    return value
