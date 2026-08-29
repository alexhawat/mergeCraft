"""Plan 13 W1.4 — post-run retry RED contracts (green after W5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.agents.post_run import run_post_run_retry_loop
from mergecraft.agents.shared import AgentResult, AgentRunContext, PostRunIssues, StopHookFailure
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path


def _tool_ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
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
        instructions=__import__(
            "mergecraft.agents.shared", fromlist=["ResolvedInstructions"]
        ).ResolvedInstructions(),
        tool_state=tool_ctx.tool_state,
    )


def test_scope_rejection_records_last_terminal_rejection(tmp_path: Path) -> None:
    from mergecraft.mcp.verdict import ensure_review_scope_for_terminal

    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.selected_mode = "Review"
    state.review_phase = "INIT"
    with pytest.raises(ValueError, match="review scope"):
        ensure_review_scope_for_terminal(state, "submit_review_verdict")
    assert getattr(state, "last_terminal_rejection", None) == "scope_unavailable"


@pytest.mark.asyncio
async def test_retry_loop_performs_zero_resumes_for_scope_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("mergecraft.agents.post_run.get_git_status", lambda: "")
    tool_ctx = _tool_ctx(tmp_path)
    tool_ctx.tool_state.selected_mode = "Review"
    tool_ctx.tool_state.review_phase = "INIT"

    prompts: list[str] = []

    async def resume(prompt: str) -> AgentResult:
        prompts.append(prompt)
        return AgentResult(success=True, terminal_submission_received=False)

    await run_post_run_retry_loop(
        _run_ctx(tool_ctx),
        initial=AgentResult(success=True, terminal_submission_received=False),
        resume=resume,
    )
    assert prompts == []


@pytest.mark.asyncio
async def test_retry_loop_still_resumes_when_no_terminal_call_attempted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("mergecraft.agents.post_run.get_git_status", lambda: "")
    tool_ctx = _tool_ctx(tmp_path)
    tool_ctx.tool_state.selected_mode = "Review"

    prompts: list[str] = []

    async def resume(prompt: str) -> AgentResult:
        prompts.append(prompt)
        return AgentResult(success=True, terminal_submission_received=False)

    await run_post_run_retry_loop(
        _run_ctx(tool_ctx),
        initial=AgentResult(success=True, terminal_submission_received=False),
        resume=resume,
    )
    assert len(prompts) == 1


@pytest.mark.asyncio
async def test_dirty_tree_remains_retryable_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("mergecraft.agents.post_run.get_git_status", lambda: " M dirty.py")
    tool_ctx = _tool_ctx(tmp_path)

    prompts: list[str] = []

    async def resume(prompt: str) -> AgentResult:
        prompts.append(prompt)
        monkeypatch.setattr("mergecraft.agents.post_run.get_git_status", lambda: "")
        return AgentResult(success=True)

    await run_post_run_retry_loop(
        _run_ctx(tool_ctx),
        initial=AgentResult(success=True),
        resume=resume,
    )
    assert len(prompts) == 1


@pytest.mark.asyncio
async def test_stop_hook_remains_retryable_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("mergecraft.agents.post_run.get_git_status", lambda: "")

    async def _collect(ctx: AgentRunContext, *, skip_summary_stale: bool = False) -> PostRunIssues:
        _ = ctx, skip_summary_stale
        return PostRunIssues(stop_hook=StopHookFailure(exit_code=1, output="blocked"))

    monkeypatch.setattr("mergecraft.agents.post_run.collect_post_run_issues", _collect)
    prompts: list[str] = []

    async def resume(prompt: str) -> AgentResult:
        prompts.append(prompt)
        return AgentResult(success=True)

    await run_post_run_retry_loop(
        _run_ctx(_tool_ctx(tmp_path)),
        initial=AgentResult(success=True),
        resume=resume,
    )
    assert len(prompts) == 1


@pytest.mark.asyncio
async def test_non_retryable_scope_records_rejection_without_resuming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D5 — the loop skips the resume and leaves publication to ``main._publish``.

    The refusal is recorded on ``tool_state``, which ``_publish`` reads to build
    the single deterministic record for the PR. Publishing a second record from
    here would be upserted over moments later, so this path must not publish.
    """
    monkeypatch.setattr("mergecraft.agents.post_run.get_git_status", lambda: "")
    tool_ctx = _tool_ctx(tmp_path)
    tool_ctx.tool_state.selected_mode = "Review"
    tool_ctx.tool_state.review_phase = "INIT"

    resumed: list[str] = []

    async def _resume(prompt: str) -> AgentResult:
        resumed.append(prompt)
        return AgentResult(success=True)

    final = await run_post_run_retry_loop(
        _run_ctx(tool_ctx),
        initial=AgentResult(success=True, terminal_submission_received=False),
        resume=_resume,
    )
    assert resumed == [], "a deterministic refusal must not spend a resume turn"
    assert tool_ctx.tool_state.last_terminal_rejection == "scope_unavailable"
    assert final.success is True
