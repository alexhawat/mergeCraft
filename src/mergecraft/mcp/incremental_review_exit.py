"""Incremental re-review scope x verdict/progress exit matrix (#SM6)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

IncrementalDiffStatus = Literal["ok", "empty", "unavailable"]


class IncrementalReviewExit(StrEnum):
    """Explicit exit for incremental mode — empty cannot masquerade as unavailable."""

    full_review_required = "full_review_required"
    delta_review = "delta_review"
    progress_only = "progress_only"
    blocked_no_verdict = "blocked_no_verdict"


@dataclass(frozen=True, slots=True)
class IncrementalExitContext:
    status: IncrementalDiffStatus
    final_summary_written: bool
    terminal_submission_received: bool
    mode: str


def classify_incremental_exit(ctx: IncrementalExitContext) -> IncrementalReviewExit:
    if ctx.mode != "IncrementalReview":
        return IncrementalReviewExit.full_review_required
    if ctx.status == "unavailable":
        return IncrementalReviewExit.full_review_required
    if ctx.status == "ok":
        return IncrementalReviewExit.delta_review
    if ctx.status == "empty":
        if ctx.final_summary_written and not ctx.terminal_submission_received:
            return IncrementalReviewExit.progress_only
        return IncrementalReviewExit.blocked_no_verdict
    return IncrementalReviewExit.full_review_required


def progress_only_may_satisfy_approval(exit_kind: IncrementalReviewExit) -> bool:
    """Progress-only incremental exit never attests approval success."""
    return exit_kind is not IncrementalReviewExit.progress_only


__all__ = [
    "IncrementalExitContext",
    "IncrementalReviewExit",
    "classify_incremental_exit",
    "progress_only_may_satisfy_approval",
]
