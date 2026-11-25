"""The Action's primary reviewer pays once for what it streamed (#1559).

A streaming attempt charges each step as it arrives and reports its whole usage
when it finishes. The final charge adds only the remainder of that same attempt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from tests.support.publication import RecordingReviewGitHub, publication_ctx, run_ctx_for

import mergecraft.main as main_mod
from mergecraft.action import review_dispatch
from mergecraft.agents.shared import AgentResult, AgentUsage, ResolvedInstructions
from mergecraft.agents.stream_budget import charge_review_stream_step
from mergecraft.config.settings import RepoInfo, RepoSettings, RunContextData
from mergecraft.review.pipeline import dispatch as pipeline_dispatch
from mergecraft.utils.run_bounds import BudgetTracker, resolve_run_bounds

if TYPE_CHECKING:
    from pathlib import Path

_STREAMING = "acme/streaming"
_AGGREGATE = "acme/aggregate"
_STREAM_TOKENS = 120_000
_STREAM_COST = 1.0


class _Reviewer:
    """Streams one step for the streaming model; only reports a total for the other."""

    name = "claude"

    async def install(self) -> None:
        return None

    async def run(self, ctx: Any) -> AgentResult:
        if ctx.resolved_model == _AGGREGATE:
            return AgentResult(
                success=True,
                usage=AgentUsage(
                    agent="claude", input_tokens=100_000, output_tokens=0, cost_usd=0.9
                ),
            )
        reason = charge_review_stream_step(
            {"input_tokens": _STREAM_TOKENS, "output_tokens": 0},
            budget_tracker=ctx.budget_tracker,
            provider_budget=None,
            stream_charges=ctx.stream_charges,
            cost_usd=_STREAM_COST,
        )
        assert reason is None
        return AgentResult(
            success=True,
            usage=AgentUsage(
                agent="claude", input_tokens=_STREAM_TOKENS, output_tokens=0, cost_usd=_STREAM_COST
            ),
        )


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> main_mod.RunContext:
    tool_context = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    tracker = BudgetTracker(resolve_run_bounds(env={}))
    run_ctx = run_ctx_for(tool_context)
    run_ctx.instructions = ResolvedInstructions(system="run start", user="review")
    run_ctx.resolved_model = _STREAMING
    run_ctx.budget_tracker = tracker
    reviewer: Any = _Reviewer()
    run = main_mod.RunContext(
        settings=RepoSettings(),
        tool_context=tool_context,
        tool_state=tool_context.tool_state,
        run_ctx=run_ctx,
        tmpdir=tool_context.tmpdir,
        budget_tracker=tracker,
        agent=reviewer,
        agent_id="claude",
    )
    run.run_context = RunContextData(
        repo=RepoInfo(owner="acme", name="demo"), repoSettings=RepoSettings()
    )
    monkeypatch.setattr(review_dispatch, "resolve_runtime_agent", lambda **_: reviewer)
    monkeypatch.setattr(
        review_dispatch, "resolve_model", lambda slug, respect_env_override=False: slug
    )
    return run


async def test_a_single_streaming_attempt_is_charged_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _run(tmp_path, monkeypatch)
    assert run.budget_tracker is not None

    slug, result = await main_mod._run_agent_task_with_deadline(run)
    main_mod._promote_and_finalize_agent_result(run, slug, result)

    assert run.budget_tracker.tokens_used == _STREAM_TOKENS
    assert run.budget_tracker.cost_used == pytest.approx(_STREAM_COST)


@pytest.mark.parametrize(
    ("attempts", "tokens", "cost"),
    [
        pytest.param([_STREAMING], _STREAM_TOKENS, _STREAM_COST, id="streaming-winner"),
        pytest.param(
            [_STREAMING, _AGGREGATE], _STREAM_TOKENS + 100_000, 1.9, id="streaming-then-aggregate"
        ),
    ],
)
async def test_a_chain_charges_the_winner_net_of_its_own_stream_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attempts: list[str],
    tokens: int,
    cost: float,
) -> None:
    run = _run(tmp_path, monkeypatch)
    run.use_model_chain = True
    assert run.budget_tracker is not None

    async def _chain(*, run_once: Any, **_kwargs: Any) -> tuple[str, AgentResult]:
        results = [await run_once(slug) for slug in attempts]
        return attempts[-1], results[-1]

    monkeypatch.setattr(pipeline_dispatch, "run_with_model_chain", _chain)

    slug, result = await main_mod._run_agent_task_with_deadline(run)
    main_mod._promote_and_finalize_agent_result(run, slug, result)

    assert run.budget_tracker.tokens_used == tokens
    assert run.budget_tracker.cost_used == pytest.approx(cost)
