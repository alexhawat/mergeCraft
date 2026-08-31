"""Merge findings from multiple reviewer-role bindings into one verdict (D6, D7, D15)."""

from __future__ import annotations

from mergecraft.review.roster_dispatch import reviewer_dispatch_batches
from mergecraft.review.terminal_submission import (
    TERMINAL_SUBMISSION_COUNT,
    ReviewerRun,
    append_degradation_to_summary,
    enrich_finding_body_with_provenance,
    format_reviewer_degradation_summary,
    merge_reviewer_findings,
    prepare_terminal_submission,
    reviewer_groups_from_runs,
    should_render_finding_provenance,
    stamp_findings_with_reviewer,
    terminal_submission_count_from_review_runs,
    verdict_from_merged_findings,
)

__all__ = [
    "TERMINAL_SUBMISSION_COUNT",
    "ReviewerRun",
    "append_degradation_to_summary",
    "enrich_finding_body_with_provenance",
    "format_reviewer_degradation_summary",
    "merge_reviewer_findings",
    "prepare_terminal_submission",
    "reviewer_dispatch_batches",
    "reviewer_groups_from_runs",
    "should_render_finding_provenance",
    "stamp_findings_with_reviewer",
    "terminal_submission_count_from_review_runs",
    "verdict_from_merged_findings",
]
