"""Every review state field needs an explicit lifetime across checkout."""

from dataclasses import fields

import pytest

from mergecraft.mcp.checkout_state import RESET_REPO_FIELDS, RESET_TOOL_FIELDS
from mergecraft.mcp.tool_state import RepoToolState, ToolState

# Run identity, operator policy, receipts, budgets and audit history outlive a checkout.
# Keep these names explicit so adding a field requires a lifetime decision here.
RETAINED_REPO_FIELDS = {
    "access",
    "default_branch",
    "dir",
    "initial_head",
    "issue_number",
    "name",
    "owner",
    "push_url",
}

RETAINED_TOOL_FIELDS = {
    "agent_deadline_s",
    "agent_diagnostic",
    "agent_sandbox_decision",
    "agent_started_monotonic",
    "attempt_id",
    "author",
    "author_association",
    "authority_trust",
    "autopromote_learnings",
    "background_processes",
    "browser_daemon",
    "capture_verdicts",
    "credential_degradations",
    "dependency_installation",
    "diff_budget_reason",
    "driver_reports_reads",
    "existing_plan_comment_id",
    "fallback_index",
    "fallback_occurred",
    "final_summary_written",
    "finalize_failure",
    "fix_labels",
    "pull_request_labels",
    "pull_request_title",
    "red_green_declaration",
    "git_show_cache",
    "had_progress_comment",
    "last_progress_body",
    "learnings_file_path",
    "learnings_persist_attempted",
    "learnings_review_delta",
    "learnings_seed",
    "linked_issues",
    "llm_review_timing",
    "model",
    "model_clamped",
    "modes",
    "offline_review",
    "on_finding",
    "oss",
    "phase_elapsed_s",
    "pr_number",
    "prepush_failure_count",
    "previous_plan_body",
    "primary_repo_key",
    "progress_comment",
    "reapproval",
    "repos",
    "requested_model",
    "review",
    "review_ignore",
    "review_mcp_names",
    "review_mcp_servers",
    "review_replies",
    "review_skill_paths",
    "review_skills_ledger",
    "review_stamp",
    "review_tree_baseline",
    "run_bound_progress_comment_id",
    "run_id",
    "run_manifest_trust",
    "scope_declaration",
    "selected_mode",
    "setup_hook_failure",
    "setup_script_skip_reason",
    "sha_pinned",
    "summary_file_path",
    "summary_persist_attempted",
    "summary_seed",
    "todo_tracker",
    "tool_calls",
    "triage",
    "trust_self_review_level",
    "trust_tier",
    "unselected_proxy_default",
    "usage_entries",
    "was_updated",
    "xrepo_learnings_file_path",
    "xrepo_learnings_persist_attempted",
    "xrepo_learnings_seed",
}


@pytest.mark.parametrize(
    ("state_type", "reset", "retained"),
    [
        (RepoToolState, set(RESET_REPO_FIELDS), RETAINED_REPO_FIELDS),
        (
            ToolState,
            set(RESET_TOOL_FIELDS)
            | {"review_phase", "checkout_scope_invalidated", "review_scope_tool_call_start"},
            RETAINED_TOOL_FIELDS,
        ),
    ],
)
def test_every_checkout_state_field_has_one_explicit_lifetime(
    state_type: type[RepoToolState] | type[ToolState], reset: set[str], retained: set[str]
) -> None:
    assert not reset & retained, "a field cannot be both reset and retained"
    assert reset | retained == {field.name for field in fields(state_type)}
