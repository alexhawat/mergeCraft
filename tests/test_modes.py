"""Unit tests for built-in mode catalogs."""

from __future__ import annotations

from mergecraft.modes import (
    NON_COMMITTING_MODES,
    PR_SUMMARY_FORMAT,
    Mode,
    compute_modes,
    modes,
)
from mergecraft.review_taxonomy import (
    BODY_ONLY_EFFORT,
    BODY_ONLY_SEVERITY,
    FINDING_CATEGORIES,
    FINDING_CONFIDENCES,
    FINDING_EFFORTS,
    FINDING_SEVERITIES,
    VERIFY_FIRST_PREAMBLE,
    WITHDRAWN_FINDINGS_HEADING,
)
from mergecraft.types import format_mcp_tool_ref

EXPECTED_MODE_NAMES = [
    "Build",
    "AddressReviews",
    "Review",
    "IncrementalReview",
    "Plan",
    "Fix",
    "ResolveConflicts",
    "Task",
]


def test_compute_modes_returns_all_built_ins() -> None:
    result = compute_modes("opencode")
    assert [m.name for m in result] == EXPECTED_MODE_NAMES
    assert all(isinstance(m, Mode) for m in result)
    assert all(m.prompt and m.description for m in result)


def test_static_modes_match_opencode_default() -> None:
    assert [m.name for m in modes] == EXPECTED_MODE_NAMES
    assert "mergecraft_checkout_pr" in (modes[0].prompt or "")


def test_claude_tool_refs_use_mcp_prefix() -> None:
    build = compute_modes("claude")[0]
    assert "mcp__mergecraft__checkout_pr" in (build.prompt or "")
    assert "mcp__mergecraft__push_branch" in (build.prompt or "")
    assert "mergecraft_checkout_pr" not in (build.prompt or "")


def test_opencode_tool_refs_use_underscore() -> None:
    build = compute_modes("opencode")[0]
    assert "mergecraft_checkout_pr" in (build.prompt or "")
    assert "mcp__mergecraft__" not in (build.prompt or "")


def test_signed_commits_swaps_commit_and_push_flow() -> None:
    unsigned = next(m for m in compute_modes("opencode", signed_commits=False) if m.name == "Build")
    signed = next(m for m in compute_modes("opencode", signed_commits=True) if m.name == "Build")
    assert "git add . && git commit" in (unsigned.prompt or "")
    assert "mergecraft_push_branch" in (unsigned.prompt or "")
    assert "mergecraft_commit_changes" in (signed.prompt or "")
    assert "no push step" in (signed.prompt or "")


def test_resolve_conflicts_signed_commits_uses_no_commit_merge() -> None:
    rc = next(
        m for m in compute_modes("claude", signed_commits=True) if m.name == "ResolveConflicts"
    )
    assert "git merge --no-commit origin/<base_branch>" in (rc.prompt or "")
    assert "mcp__mergecraft__commit_changes" in (rc.prompt or "")


def test_non_committing_modes() -> None:
    assert frozenset({"Review", "IncrementalReview", "Plan"}) == NON_COMMITTING_MODES


def test_pr_summary_format_embedded_in_review_modes() -> None:
    assert "### Default format" in PR_SUMMARY_FORMAT
    assert "{head_sha_short}" in PR_SUMMARY_FORMAT
    for name in ("Review", "IncrementalReview"):
        mode = next(m for m in modes if m.name == name)
        assert "### Default format" in (mode.prompt or "")
        assert "Nitpicks" in (mode.prompt or "")


def test_pr_summary_format_names_every_taxonomy_value() -> None:
    """The prompt is the only consumer of the taxonomy — it must name all of it."""
    for value in (*FINDING_CATEGORIES, *FINDING_SEVERITIES, *FINDING_EFFORTS):
        assert value in PR_SUMMARY_FORMAT, value


def test_fix_all_block_carries_verify_first_preamble_verbatim() -> None:
    assert VERIFY_FIRST_PREAMBLE in PR_SUMMARY_FORMAT
    assert "### 🤖 Fix all findings" in PR_SUMMARY_FORMAT


def test_pre_merge_checks_table_present() -> None:
    assert "### 🚥 Pre-merge checks" in PR_SUMMARY_FORMAT
    for row in (
        "| Title |",
        "| Description |",
        "| Linked issues |",
        "| Scope |",
        "| Analyzers |",
    ):
        assert row in PR_SUMMARY_FORMAT, row


def test_pr_summary_format_names_every_confidence_value() -> None:
    for value in FINDING_CONFIDENCES:
        assert value in PR_SUMMARY_FORMAT, value


def test_pr_summary_format_includes_mechanical_findings_section() -> None:
    assert "### 🔧 Mechanical findings" in PR_SUMMARY_FORMAT


def test_review_modes_reference_analyzer_tools() -> None:
    for agent, prefix in (("claude", "mcp__mergecraft__"), ("opencode", "mergecraft_")):
        for name in ("Review", "IncrementalReview"):
            prompt = next(m for m in compute_modes(agent) if m.name == name).prompt or ""
            assert f"{prefix}run_analyzers" in prompt, (agent, name)
            assert "analyzer_findings" in prompt, (agent, name)
            assert "mergecraft-verifier" in prompt, (agent, name)


def test_trivial_findings_routed_to_nitpicks() -> None:
    assert BODY_ONLY_SEVERITY in PR_SUMMARY_FORMAT
    assert BODY_ONLY_EFFORT in PR_SUMMARY_FORMAT
    assert "never an inline comment" in PR_SUMMARY_FORMAT


def test_review_modes_run_static_checks_and_read_withdrawn_findings() -> None:
    for agent, expected_ref in (("claude", "mcp__mergecraft__"), ("opencode", "mergecraft_")):
        for name in ("Review", "IncrementalReview"):
            prompt = next(m for m in compute_modes(agent) if m.name == name).prompt or ""
            assert f"{expected_ref}run_static_checks" in prompt, (agent, name)
            assert WITHDRAWN_FINDINGS_HEADING in prompt, (agent, name)


def test_address_reviews_records_withdrawn_findings() -> None:
    prompt = next(m for m in modes if m.name == "AddressReviews").prompt or ""
    assert WITHDRAWN_FINDINGS_HEADING in prompt


def test_review_mode_has_data_integrity_and_copy_lenses() -> None:
    prompt = next(m for m in modes if m.name == "Review").prompt or ""
    assert "**data integrity & atomicity**" in prompt
    assert "**copy vs code**" in prompt


def test_mergecraft_reviewer_subagent_referenced() -> None:
    build = next(m for m in modes if m.name == "Build")
    review = next(m for m in modes if m.name == "Review")
    assert "mergecraft-reviewer" in (build.prompt or "")
    assert "mergecraft-reviewer" in (review.prompt or "")


def test_format_mcp_tool_ref_helpers() -> None:
    assert format_mcp_tool_ref("claude", "select_mode") == "mcp__mergecraft__select_mode"
    assert format_mcp_tool_ref("opencode", "select_mode") == "mergecraft_select_mode"


def test_expanded_prompts_have_no_template_markers() -> None:
    for agent in ("claude", "opencode"):
        for signed in (False, True):
            for mode in compute_modes(agent, signed_commits=signed):
                prompt = mode.prompt or ""
                assert "${" not in prompt, mode.name
                assert "<<<NEST>>>" not in prompt, mode.name
