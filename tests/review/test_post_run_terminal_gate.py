"""VP2 fail-closed post-run gate — unsubmitted review without a progress comment.

Wave plan: ``.ignorelocal/01-review-integrity-wave-plan.md`` (VP2.1 RED, VP2.2
impl). V4: ``get_unsubmitted_review`` must gate Review / IncrementalReview even
when ``had_progress_comment`` is false, and retry exhaustion must not fall
through to ``passed``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.agents.post_run import get_unsubmitted_review, run_post_run_retry_loop
from mergecraft.agents.shared import (
    MAX_POST_RUN_RETRIES,
    AgentResult,
    AgentRunContext,
    ResolvedInstructions,
)
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import ReviewRecord, TerminalSubmission, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.run_outcome import RunOutcome, run_succeeded_for_outcome
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

_VP22 = pytest.mark.xfail(
    reason="green after VP2.2: fail-closed terminal verdict",
    strict=False,
)

_MISSING_VERDICT_REASON = "no terminal review verdict was submitted for this attempt"


def _tool_ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request"),
            shell="restricted",
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


def _run_ctx(tool_ctx: ToolContext) -> AgentRunContext:
    return AgentRunContext(
        payload=tool_ctx.payload,
        mcp_server_url=tool_ctx.mcp_server_url,
        tmpdir=tool_ctx.tmpdir,
        subagent_denied_tools=(),
        instructions=ResolvedInstructions(),
        tool_state=tool_ctx.tool_state,
    )


def _classify(result: AgentResult, *, mode: str = "Review") -> tuple[RunOutcome, str | None]:
    from mergecraft.main_outcome import _classify_outcome

    outcome, reason = _classify_outcome(
        result=result,
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
        mode=mode,
    )
    return outcome, reason


def _recorded_submission() -> TerminalSubmission:
    return TerminalSubmission(
        id="sub-recorded",
        verdict="approve",
        summary="No blocking issues in the diff.",
        findings=[],
        payload_hash="abc",
        submitted_at="2026-08-16T00:00:00+00:00",
        attempt_id=0,
    )


@_VP22
def test_unsubmitted_review_without_progress_comment_still_gates(tmp_path: Path) -> None:
    """V4: Review / IncrementalReview gate on ``terminal_submission``, not ``review``.

    ``had_progress_comment`` is false. A legacy ``ReviewRecord`` must not satisfy
    the gate — only a recorded ``TerminalSubmission`` does.
    """
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.had_progress_comment = False
    state.review = ReviewRecord(id=99, node_id="legacy", reviewed_sha="abc")
    assert state.terminal_submission is None

    state.selected_mode = "Review"
    assert get_unsubmitted_review(state) == "Review"

    state.selected_mode = "IncrementalReview"
    state.final_summary_written = False
    assert get_unsubmitted_review(state) == "IncrementalReview"

    state.terminal_submission = _recorded_submission()
    state.selected_mode = "Review"
    assert get_unsubmitted_review(state) is None
    state.selected_mode = "IncrementalReview"
    assert get_unsubmitted_review(state) is None


@_VP22
@pytest.mark.asyncio
async def test_retry_exhaustion_yields_inconclusive_not_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V4: exhausting the post-run retry loop must not fall through to ``passed``."""
    monkeypatch.setattr("mergecraft.agents.post_run.get_git_status", lambda: "")

    tool_ctx = _tool_ctx(tmp_path)
    tool_ctx.tool_state.selected_mode = "Review"
    tool_ctx.tool_state.had_progress_comment = False
    assert tool_ctx.tool_state.terminal_submission is None

    prompts: list[str] = []

    async def resume(prompt: str) -> AgentResult:
        prompts.append(prompt)
        return AgentResult(
            success=True,
            output="still no terminal verdict",
            terminal_submission_received=False,
        )

    final = await run_post_run_retry_loop(
        _run_ctx(tool_ctx),
        initial=AgentResult(success=True, output="done", terminal_submission_received=False),
        resume=resume,
    )
    assert len(prompts) == MAX_POST_RUN_RETRIES
    assert final.terminal_submission_received is False

    outcome, reason = _classify(final, mode="Review")
    assert outcome is not RunOutcome.passed
    assert outcome is RunOutcome.inconclusive
    assert outcome is not RunOutcome.failed
    assert reason == _MISSING_VERDICT_REASON
    assert run_succeeded_for_outcome(outcome) is False
