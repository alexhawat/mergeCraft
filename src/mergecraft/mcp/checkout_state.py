"""Invalidate revision-bound review evidence before checkout changes the workspace."""

from __future__ import annotations

from mergecraft.mcp.tool_state import RepoToolState, ToolState, primary_repo_state

# Every field must be classified by the checkout state contract test.
RESET_REPO_FIELDS = (
    "checkout_sha",
    "reviewed_merge_base",
    "before_sha",
    "push_dest",
    "diff_path",
    "diff_coverage",
    "commentable_lines_by_file",
    "commentable_lines_pull_number",
    "commentable_lines_checkout_sha",
    "last_reviewed_sha",
    "incremental_diff_path",
    "incremental_changed_paths",
)

RESET_TOOL_FIELDS = (
    "output",
    "scope_provenance",
    "review_scope",
    "pending_review_publication",
    "prepared_run_packet",
    "terminal_submission",
    "terminal_submission_conflict",
    "approval",
    "review_publication_entrypoint",
    "review_publication_sticky_only",
    "review_inline_comments_demoted",
    "review_comment_fallback_applied",
    "review_body_truncated",
    "terminal_publication_failed",
    "terminal_publication_mismatch",
    "publication_incomplete",
    "reviewer_dispatch_errors",
    "reviewer_dispatch_runs",
    "active_file_groups",
    "file_group_row_owners",
    "confirmed_findings",
    "agent_findings",
    "analyzer_run",
    "analyzer_evidence",
    "ci_evidence",
    "red_green",
    "verified_ids",
    "withdrawn_fingerprints",
    "pinned_analyzer_settings",
    "finding_ledger",
    "finding_ledger_loaded",
    "lens_routing_decision",
    "dispatched_lens_ids",
    "static_checks_ran",
    "static_checks",
    "policy_evaluation",
    "linked_repo_base_manifest",
    "linked_repo_review",
    "coverage",
    "ignored_review_paths",
    "diff_coverage_nudge_sent",
    "review_round_index",
    "review_round_cap_announced",
    "last_terminal_rejection",
    "lite_review",
)


def invalidate_checkout_review_state(state: ToolState) -> None:
    """Leave a failed/restarted checkout without publishable scope or cached proof.

    Run identity, trust, pinned configuration, budgets, usage and the complete tool
    audit trail survive. Revision-specific proof must be collected again. Published
    review receipts are retained; checkout refuses to start once one exists.
    """
    primary = primary_repo_state(state)
    empty_repo = RepoToolState(
        owner=primary.owner, name=primary.name, dir=primary.dir, access=primary.access
    )
    for name in RESET_REPO_FIELDS:
        setattr(primary, name, getattr(empty_repo, name))
    empty = ToolState(repos={}, primary_repo_key="")
    for name in RESET_TOOL_FIELDS:
        setattr(state, name, getattr(empty, name))
    from mergecraft.mcp.review_phase_machine import reset_review_phase_on_scope_invalidate

    reset_review_phase_on_scope_invalidate(state)
    state.checkout_scope_invalidated = True
    # Keep earlier calls for the security audit, but they cannot prove that the
    # reviewer read the new revision or its newly materialized diff.
    state.review_scope_tool_call_start = len(state.tool_calls)
