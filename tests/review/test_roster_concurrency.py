"""Real roster dispatch overlaps peers and isolates failures across levels."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.agents.registry import ResolvedAgentModel
from mergecraft.agents.shared import AgentResult, ResolvedInstructions
from mergecraft.config.settings import load_repo_settings
from mergecraft.mcp.tool_state import record_reviewer_dispatch_error, record_reviewer_dispatch_run
from mergecraft.review.roster_execution import run_pending_roster_reviewers
from tests.cli.support_agent_roster import DEFAULT_MODELS_YAML, write_config
from tests.support.publication import RecordingReviewGitHub, publication_ctx, run_ctx_for

if TYPE_CHECKING:
    from pathlib import Path


async def _run_roster(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent: Any):
    write_config(
        tmp_path,
        DEFAULT_MODELS_YAML
        + """
agents:
  reviewer:
    modelChain: [anthropic/claude-sonnet]
  reviewer2:
    role: reviewer
    modelChain: [mock/second]
  reviewer3:
    role: reviewer
    modelChain: [mock/third]
  reviewer4:
    role: reviewer
    after: reviewer2
    modelChain: [mock/fourth]
""",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.resolve_runtime_agent", lambda **_: agent
    )
    monkeypatch.setattr("mergecraft.review.roster_execution.resolve_model", lambda slug, **_: slug)
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.credential_status_for_slug",
        lambda *a, **k: type("Status", (), {"available": True})(),
    )
    monkeypatch.setattr(
        "mergecraft.agents.registry.resolve_agent_model",
        lambda binding, **_: ResolvedAgentModel(
            requested_model=binding.model_chain[0],
            executed_model=binding.model_chain[0],
            recorded_model=binding.model_chain[0],
            dispatched_model=binding.model_chain[0],
        ),
    )
    settings = load_repo_settings(root=tmp_path)
    ctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    summary = await run_pending_roster_reviewers(
        tool_context=ctx,
        base_run_ctx=run_ctx_for(ctx),
        settings=settings,
        payload={"event": {"trigger": "unknown"}},
        repo_root=tmp_path,
        per_reviewer_timeout_s=2.0,
        instructions_for={"opencode": ResolvedInstructions(system="base", user="review")}.get,
    )
    return summary, ctx.tool_state


@pytest.mark.parametrize(
    "failure",
    [None, "result", "exception", "recorded", "cancelled"],
    ids=["success", "failed", "raised", "recorded-error", "cancelled-peer"],
)
async def test_peers_overlap_and_later_level_runs_after_all_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    started: set[str] = set()
    finished: set[str] = set()
    peers_started = asyncio.Event()

    class Agent:
        name = "opencode"

        async def run(self, ctx: Any) -> AgentResult:
            model = ctx.resolved_model
            started.add(model)
            if model == "mock/fourth":
                assert finished == {"mock/second", "mock/third"}
            else:
                if {"mock/second", "mock/third"} <= started:
                    peers_started.set()
                # A serial dispatcher cannot complete this rendezvous.
                await asyncio.wait_for(peers_started.wait(), timeout=1.0)
            finished.add(model)
            if model == "mock/second" and failure:
                if failure == "exception":
                    raise RuntimeError("second provider failed")
                if failure == "cancelled":
                    raise asyncio.CancelledError("second provider failed")
                if failure == "recorded":
                    record_reviewer_dispatch_error(
                        ctx.tool_state, agent_id="reviewer2", reason="second provider failed"
                    )
                    return AgentResult(success=True)
                return AgentResult(success=False, error="second provider failed")
            agent_id = {
                "mock/second": "reviewer2",
                "mock/third": "reviewer3",
                "mock/fourth": "reviewer4",
            }[model]
            record_reviewer_dispatch_run(
                ctx.tool_state,
                agent_id=agent_id,
                findings=[{"path": f"{agent_id}.py", "body": agent_id}],
                model_slug=model,
            )
            return AgentResult(success=True)

    summary, state = await _run_roster(tmp_path, monkeypatch, Agent())

    assert started == {"mock/second", "mock/third", "mock/fourth"}
    expected = (
        ("reviewer2", "reviewer3", "reviewer4") if failure is None else ("reviewer3", "reviewer4")
    )
    assert summary.dispatched_agent_ids == expected
    assert (summary.hard_error is not None) == (failure is not None)
    if failure:
        assert "reviewer2" in state.reviewer_dispatch_errors
        if failure != "cancelled":
            assert "second provider failed" in state.reviewer_dispatch_errors["reviewer2"]
    for run in state.reviewer_dispatch_runs:
        assert [row["body"] for row in run.findings] == [run.agent_id]


async def test_parallel_reviewers_cannot_claim_each_others_unattributed_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    both_started = asyncio.Event()
    count = 0

    class Agent:
        name = "opencode"

        async def run(self, ctx: Any) -> AgentResult:
            nonlocal count
            if ctx.resolved_model == "mock/fourth":
                return AgentResult(success=True)
            count += 1
            if count == 2:
                both_started.set()
            await both_started.wait()
            ctx.tool_state.agent_findings.append(
                {"fingerprint": ctx.resolved_model, "body": ctx.resolved_model}
            )
            return AgentResult(success=True)

    summary, state = await _run_roster(tmp_path, monkeypatch, Agent())

    assert summary.hard_error is not None
    assert "reviewer2" in summary.hard_error
    assert "reviewer3" in summary.hard_error
    assert summary.dispatched_agent_ids == ("reviewer4",)
    assert all(not run.findings for run in state.reviewer_dispatch_runs)
    assert len(state.agent_findings) == 2, "unattributed findings must still reach the packet"


async def test_cancelling_the_roster_cleans_up_every_peer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    both_started = asyncio.Event()
    started: set[str] = set()
    cleaned_up: set[str] = set()

    class Agent:
        name = "opencode"

        async def run(self, ctx: Any) -> AgentResult:
            model = ctx.resolved_model
            started.add(model)
            if len(started) == 2:
                both_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned_up.add(model)
            return AgentResult(success=True)

    task = asyncio.create_task(_run_roster(tmp_path, monkeypatch, Agent()))
    try:
        await asyncio.wait_for(both_started.wait(), timeout=1.0)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert started == {"mock/second", "mock/third"}
    assert cleaned_up == started
