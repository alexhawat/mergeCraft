"""VP3 attempt attribution — V7 verdict freshness.

Wave plan: ``.ignorelocal/01-review-integrity-wave-plan.md`` (VP3 File 3,
VP3.2 impl; xfail markers cleared after VP3.2).

**V7**: bind the terminal verdict to the attempt that produced it. Stamp
``attempt_id`` when the model chain starts an attempt (beside
``fallback_index`` in ``utils/agent_resolve.py``), record it on
``TerminalSubmission``, and refuse to treat a structural result whose
``attempt_id`` does not match the current attempt as satisfying it.

Pairs with HA2 ``stale_attempt``: a result from a previous attempt must
not be reused by a later one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.agents.post_run import finalize_agent_result
from mergecraft.agents.shared import AgentResult, AgentRunContext, ResolvedInstructions
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.tool_state import TerminalSubmission, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=7, is_pr=True),
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


def _approve_payload() -> dict[str, str | list[object]]:
    return {
        "verdict": "approve",
        "summary": "No blocking issues in the diff.",
        "findings": [],
    }


@pytest.mark.asyncio
async def test_verdict_is_bound_to_its_attempt(tmp_path: Path) -> None:
    """V7: ``TerminalSubmission.attempt_id`` is the id stamped when the attempt starts.

    ``stamp_attempt_id`` lives beside ``fallback_index`` in
    ``utils/agent_resolve.py``. The recorder must copy that stamp onto
    the submission — not invent a second id at submit time.
    """
    from mergecraft.mcp.verdict import submit_review_verdict_tool
    from mergecraft.utils.agent_resolve import stamp_attempt_id

    ctx = _ctx(tmp_path)
    stamp_attempt_id(ctx.tool_state, attempt_id=2, fallback_index=2)
    assert ctx.tool_state.attempt_id == 2
    assert ctx.tool_state.fallback_index == 2

    result = await submit_review_verdict_tool(ctx).execute(_approve_payload())
    assert result.is_error is False
    recorded = ctx.tool_state.terminal_submission
    assert recorded is not None
    assert isinstance(recorded, TerminalSubmission)
    assert recorded.attempt_id == 2

    finalized = await finalize_agent_result(_run_ctx(ctx), AgentResult(success=True))
    assert finalized.terminal_submission_received is True
    assert finalized.diagnostics.get("attempt_id") == 2


@pytest.mark.asyncio
async def test_stale_structural_result_is_not_reused(tmp_path: Path) -> None:
    """A result whose ``attempt_id`` does not match the current attempt does not satisfy it.

    Guard-deletion: if the freshness check is removed, ``finalize_agent_result``
    would still set ``terminal_submission_received=True`` for a leftover
    attempt-0 submission while the chain is on attempt 1. Pairs with HA2
    ``stale_attempt``.
    """
    from mergecraft.mcp.verdict import verdict_satisfies_attempt
    from mergecraft.utils.agent_resolve import stamp_attempt_id

    ctx = _ctx(tmp_path)
    stale = TerminalSubmission(
        id="attempt-0-submission",
        verdict="approve",
        summary="cached review from attempt 0",
        findings=[],
        payload_hash="abc",
        submitted_at="2026-08-16T00:00:00+00:00",
        attempt_id=0,
    )
    ctx.tool_state.terminal_submission = stale
    stamp_attempt_id(ctx.tool_state, attempt_id=1, fallback_index=1)

    assert verdict_satisfies_attempt(stale, current_attempt_id=1) is False
    assert verdict_satisfies_attempt(stale, current_attempt_id=0) is True

    finalized = await finalize_agent_result(_run_ctx(ctx), AgentResult(success=True))
    assert finalized.terminal_submission_received is False, (
        "stale TerminalSubmission must not satisfy the current attempt"
    )
    assert finalized.terminal_submission_id is None
