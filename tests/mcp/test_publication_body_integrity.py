"""W1.2 — the published body is the terminal body (wave plan 14, implementation W3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.publication_attribution.support import (
    PROBE_BODY,
    PROBE_INLINE_BODY,
    RaceGitHub,
    RecordingGitHub,
    bind_terminal_submission,
    publication_ctx,
)
from tests.support.tool_context import github_client_from_ctx

from mergecraft.mcp.review import (
    _publish_github_review,
    create_pull_request_review_tool,
    publish_pull_request_review,
)
from mergecraft.mcp.tool_state import ReviewRecord
from mergecraft.mcp.verdict import ReviewPhase, register_review_scope
from mergecraft.review.terminal_submission import (
    ReviewerRun,
    terminal_submission_count_from_review_runs,
)

if TYPE_CHECKING:
    from pathlib import Path

_REAL_SUMMARY = (
    "## Review findings\n\n"
    "- **Major** `src/checkout.py:147` — config guard blocks publication on checkout.\n"
)


@pytest.mark.asyncio
async def test_create_review_body_equals_terminal_submission_summary(tmp_path: Path) -> None:
    """D4 — SCM ``create_review`` kwargs must carry the terminal submission body."""
    github = RecordingGitHub()
    ctx = publication_ctx(tmp_path, github=github)
    bind_terminal_submission(ctx, summary=_REAL_SUMMARY, verdict="request_changes")
    register_review_scope(
        ctx.tool_state,
        diff_path=str(tmp_path / "diff.patch"),
        provenance="checkout",
    )
    ctx.tool_state.review_phase = ReviewPhase.SUBMIT.value

    await _publish_github_review(
        ctx,
        {
            "pull_number": 7,
            "body": _REAL_SUMMARY,
            "request_changes": True,
            "comments": [],
        },
    )
    payload = github_client_from_ctx(ctx).review_payloads[-1]  # type: ignore[attr-defined]
    assert _REAL_SUMMARY.strip() in str(payload.get("body") or "")
    assert PROBE_BODY not in str(payload.get("body") or "")


@pytest.mark.asyncio
async def test_probe_body_with_bound_terminal_submission_is_hard_failure(
    tmp_path: Path,
) -> None:
    """D4 — placeholder bodies must raise at payload construction, not publish."""
    github = RecordingGitHub()
    ctx = publication_ctx(tmp_path, github=github)
    bind_terminal_submission(ctx, summary=_REAL_SUMMARY, verdict="request_changes")
    register_review_scope(
        ctx.tool_state,
        diff_path=str(tmp_path / "diff.patch"),
        provenance="checkout",
    )
    ctx.tool_state.review_phase = ReviewPhase.SUBMIT.value

    with pytest.raises(ValueError, match=r"(?i)probe|terminal|submission"):
        await _publish_github_review(
            ctx,
            {
                "pull_number": 7,
                "body": PROBE_BODY,
                "request_changes": True,
            },
        )
    assert github.review_payloads == []


@pytest.mark.asyncio
async def test_572_race_replay_produces_one_review_with_real_findings(tmp_path: Path) -> None:
    """D5 — inline 422 racing a body-only probe must leave one review carrying findings."""
    github = RaceGitHub()
    ctx = publication_ctx(tmp_path, github=github, checkout_sha="e656debc")
    bind_terminal_submission(ctx, summary=_REAL_SUMMARY, verdict="request_changes")
    register_review_scope(
        ctx.tool_state,
        diff_path=str(tmp_path / "diff.patch"),
        provenance="checkout",
    )
    ctx.tool_state.review_phase = ReviewPhase.SUBMIT.value

    tool = create_pull_request_review_tool(ctx)
    await tool.execute(
        {
            "pull_number": 7,
            "body": _REAL_SUMMARY,
            "request_changes": True,
            "comments": [
                {
                    "path": "src/checkout.py",
                    "line": 147,
                    "body": PROBE_INLINE_BODY,
                }
            ],
        },
    )
    second = await tool.execute(
        {
            "pull_number": 7,
            "body": PROBE_BODY,
            "request_changes": True,
        },
    )
    if hasattr(second, "is_error") and second.is_error:
        pytest.fail(f"second publish must short-circuit, not error: {second}")

    assert github.successful_reviews == 1
    final_body = str(github.review_payloads[-1].get("body") or "")
    assert PROBE_BODY not in final_body
    assert "config guard blocks publication" in final_body


@pytest.mark.asyncio
async def test_second_publish_same_commit_posts_nothing_and_reports_existing_review(
    tmp_path: Path,
) -> None:
    """D5 — idempotent per ``(pull_number, commit_id)``, not verdict."""
    github = RecordingGitHub()
    ctx = publication_ctx(tmp_path, github=github, checkout_sha="deadbeef")
    bind_terminal_submission(ctx, summary=_REAL_SUMMARY, verdict="request_changes")
    register_review_scope(
        ctx.tool_state,
        diff_path=str(tmp_path / "diff.patch"),
        provenance="checkout",
    )
    ctx.tool_state.review_phase = ReviewPhase.SUBMIT.value

    first = await publish_pull_request_review(ctx)
    assert first["success"] is True
    assert len(github.review_payloads) == 1

    ctx.tool_state.terminal_submission = bind_terminal_submission(
        ctx,
        summary="Different verdict attempt",
        verdict="approve",
    )
    second = await publish_pull_request_review(ctx)
    assert second.get("skipped") is True
    assert "review" in str(second.get("reason") or "").lower()
    assert len(github.review_payloads) == 1


@pytest.mark.asyncio
async def test_demoted_inline_comments_survive_in_final_review_body(tmp_path: Path) -> None:
    """422 recovery must move inline findings into the body, not drop them."""
    github = RecordingGitHub(comment_422_without_index=True)
    ctx = publication_ctx(tmp_path, github=github)
    bind_terminal_submission(ctx, summary="Summary preamble.", verdict="request_changes")
    register_review_scope(
        ctx.tool_state,
        diff_path=str(tmp_path / "diff.patch"),
        provenance="checkout",
    )
    ctx.tool_state.review_phase = ReviewPhase.SUBMIT.value

    await _publish_github_review(
        ctx,
        {
            "pull_number": 7,
            "body": "Summary preamble.",
            "request_changes": True,
            "comments": [
                {
                    "path": "src/in_diff.py",
                    "line": 10,
                    "body": "Demoted inline finding must remain visible.",
                }
            ],
        },
    )
    final_body = str(github.review_payloads[-1].get("body") or "").lower()
    assert "demoted inline finding must remain visible" in final_body


def test_multi_reviewer_run_still_has_one_terminal_submission() -> None:
    """D13 — plan 11 D7 cardinality is unchanged (regression guard)."""

    runs = [
        ReviewerRun(agent_id="mergecraft-reviewer", findings=[{"path": "a.py", "body": "one"}]),
        ReviewerRun(agent_id="reviewer2", findings=[{"path": "b.py", "body": "two"}]),
    ]
    assert terminal_submission_count_from_review_runs(runs) == 1


@pytest.mark.asyncio
async def test_create_pull_request_review_sha_guard_skips_duplicate_on_tool_path(
    tmp_path: Path,
) -> None:
    """Existing tool-path guard — baseline for D5 moving to both entrypoints."""
    import json

    github = RecordingGitHub()
    ctx = publication_ctx(tmp_path, github=github, checkout_sha="abc123")
    bind_terminal_submission(ctx, summary=_REAL_SUMMARY, verdict="request_changes")
    register_review_scope(
        ctx.tool_state,
        diff_path=str(tmp_path / "diff.patch"),
        provenance="checkout",
    )
    ctx.tool_state.review = ReviewRecord(id=99, node_id="n99", reviewed_sha="abc123")

    result = await create_pull_request_review_tool(ctx).execute(
        {"pull_number": 7, "body": PROBE_BODY, "request_changes": True},
    )
    assert result.is_error is False
    parsed = json.loads(result.content[0]["text"])
    assert parsed.get("skipped") is True
    assert github.review_payloads == []
