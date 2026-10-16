"""One bounded follow-up hands the reviewer exactly the hunks it never received.

Before finalizing, when changed hunks remain uncovered and the run still has budget, the
post-run loop sends **one** follow-up turn that lists those hunks (and only those). The
hunks it handed back count as delivered. It never fires twice, never fires without
budget, and never fires when nothing is uncovered. While it is open the reviewer may
replace its recorded verdict — a follow-up that cannot change a verdict is not a review
step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.agents.post_run import run_post_run_retry_loop
from mergecraft.agents.shared import AgentResult
from tests.support.publication import (
    APP_DIFF,
    RecordingReviewGitHub,
    publication_ctx,
    run_ctx_for,
    submit_verdict,
    unified_diff,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.mcp.context import ToolContext

_MISSING = unified_diff("src/never_delivered.py", start=10, count=5)


@pytest.fixture(autouse=True)
def _clean_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mergecraft.agents.post_run.get_git_status", lambda: "")


async def _ctx_with_a_gap(tmp_path: Path) -> ToolContext:
    ctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    ctx.tool_state.coverage.authoritative_diff = APP_DIFF + _MISSING
    await submit_verdict(ctx, "approve", [])
    return ctx


class _Resume:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> AgentResult:
        self.prompts.append(prompt)
        return AgentResult(success=True, output="read them", terminal_submission_received=True)


async def _run(ctx: ToolContext, resume: _Resume) -> AgentResult:
    return await run_post_run_retry_loop(
        run_ctx_for(ctx),
        initial=AgentResult(success=True, output="done", terminal_submission_received=True),
        resume=resume,
    )


async def test_the_follow_up_lists_exactly_the_uncovered_hunks(tmp_path: Path) -> None:
    ctx = await _ctx_with_a_gap(tmp_path)
    resume = _Resume()

    await _run(ctx, resume)

    assert len(resume.prompts) == 1
    prompt = resume.prompts[0]
    assert "src/never_delivered.py" in prompt
    assert "10" in prompt
    assert "src/app.py" not in prompt, "a hunk the reviewer already received is not re-sent"
    assert "added 10" in prompt, "the follow-up carries the hunk's lines, not just its range"


async def test_the_hunks_handed_back_count_as_covered_afterwards(tmp_path: Path) -> None:
    from mergecraft.evidence.coverage import coverage_section_for_state

    ctx = await _ctx_with_a_gap(tmp_path)
    before = coverage_section_for_state(ctx.tool_state)
    assert before is not None
    assert before.complete is False

    await _run(ctx, _Resume())

    after = coverage_section_for_state(ctx.tool_state)
    assert after is not None
    assert after.complete is True
    assert after.hunks_covered == after.hunks_total == 2


async def test_the_follow_up_fires_at_most_once(tmp_path: Path) -> None:
    ctx = await _ctx_with_a_gap(tmp_path)
    resume = _Resume()

    await _run(ctx, resume)
    await _run(ctx, resume)

    assert len(resume.prompts) == 1


async def test_no_gap_means_no_follow_up(tmp_path: Path) -> None:
    ctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    ctx.tool_state.coverage.authoritative_diff = APP_DIFF
    await submit_verdict(ctx, "approve", [])
    resume = _Resume()

    await _run(ctx, resume)

    assert resume.prompts == []


async def test_no_budget_means_no_follow_up_and_the_cause_is_named(tmp_path: Path) -> None:
    from mergecraft.evidence.coverage import coverage_section_for_state

    class _Exhausted:
        last_exhausted = RuntimeError("token budget exhausted")

    ctx = await _ctx_with_a_gap(tmp_path)
    ctx.tool_state.coverage.budget_tracker = _Exhausted()
    resume = _Resume()

    await _run(ctx, resume)

    assert resume.prompts == []
    section = coverage_section_for_state(ctx.tool_state)
    assert section is not None
    assert [r.cause for r in section.uncovered] == ["budget_exhausted"]


async def test_files_the_api_sent_no_patch_for_are_not_followed_up(tmp_path: Path) -> None:
    """A follow-up can only hand back lines that exist; an unseen file stays uncovered."""
    from mergecraft.evidence.coverage import coverage_section_for_state

    ctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    ctx.tool_state.coverage.authoritative_diff = APP_DIFF
    ctx.tool_state.coverage.unreviewable_paths = ["big/huge.py"]
    await submit_verdict(ctx, "approve", [])
    resume = _Resume()

    await _run(ctx, resume)

    assert resume.prompts == []
    section = coverage_section_for_state(ctx.tool_state)
    assert section is not None
    assert [r.cause for r in section.uncovered] == ["no_inline_patch"]


async def test_the_reviewer_may_replace_its_verdict_during_the_follow_up(
    tmp_path: Path,
) -> None:
    ctx = await _ctx_with_a_gap(tmp_path)
    first = ctx.tool_state.terminal_submission
    assert first is not None
    assert first.verdict == "approve"

    class _Revises(_Resume):
        async def __call__(self, prompt: str) -> AgentResult:
            from tests.support.publication import finding

            await submit_verdict(
                ctx,
                "request_changes",
                [finding("Verified Major: the new hunk drops the retry.", line=12)],
            )
            return await super().__call__(prompt)

    await _run(ctx, _Revises())

    revised: Any = ctx.tool_state.terminal_submission
    assert revised is not None
    assert revised.verdict == "request_changes"
    assert ctx.tool_state.terminal_submission_conflict is False


async def test_outside_the_follow_up_a_different_verdict_is_still_a_conflict(
    tmp_path: Path,
) -> None:
    from mergecraft.mcp.verdict import submit_review_verdict_tool
    from tests.support.publication import finding

    ctx = await _ctx_with_a_gap(tmp_path)

    result = await submit_review_verdict_tool(ctx).execute(
        {
            "verdict": "request_changes",
            "summary": "changed my mind",
            "findings": [finding("Verified Major: x.", line=12)],
        }
    )

    assert result.is_error is True
    assert ctx.tool_state.terminal_submission_conflict is True
