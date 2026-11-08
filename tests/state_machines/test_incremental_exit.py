"""Incremental scope x exit matrix."""

from __future__ import annotations

from mergecraft.mcp.incremental_review_exit import (
    IncrementalExitContext,
    IncrementalReviewExit,
    classify_incremental_exit,
    progress_only_may_satisfy_approval,
)


def test_empty_with_progress_only() -> None:
    exit_kind = classify_incremental_exit(
        IncrementalExitContext(
            status="empty",
            final_summary_written=True,
            terminal_submission_received=False,
            mode="IncrementalReview",
        )
    )
    assert exit_kind is IncrementalReviewExit.progress_only
    assert progress_only_may_satisfy_approval(exit_kind) is False


def test_empty_without_summary_blocked() -> None:
    exit_kind = classify_incremental_exit(
        IncrementalExitContext(
            status="empty",
            final_summary_written=False,
            terminal_submission_received=False,
            mode="IncrementalReview",
        )
    )
    assert exit_kind is IncrementalReviewExit.blocked_no_verdict


def test_unavailable_not_confused_with_empty() -> None:
    exit_kind = classify_incremental_exit(
        IncrementalExitContext(
            status="unavailable",
            final_summary_written=True,
            terminal_submission_received=False,
            mode="IncrementalReview",
        )
    )
    assert exit_kind is IncrementalReviewExit.full_review_required
