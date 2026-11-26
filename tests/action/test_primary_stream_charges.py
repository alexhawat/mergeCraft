"""The Action's primary reviewer pays once for what it streamed (#1559).

A streaming attempt charges each step as it arrives and reports its whole usage
when it finishes. The final charge adds only the remainder of that same attempt.

Every attempt of a model chain is accounted for, not only the winner (#1586):
each one is priced at the model it ran, listed as its own usage row and charged
net of its own stream, including an attempt that failed and reported its usage
only when it finished.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest
from tests.support.chain_usage import (
    CHAIN_SCRIPTS,
    ScriptedAttempt,
    expected_cost,
    install_chain_rates,
)
from tests.support.publication import RecordingReviewGitHub, publication_ctx, run_ctx_for

import mergecraft.main as main_mod
from mergecraft.action import review_dispatch
from mergecraft.agents.shared import AgentResult, AgentUsage, ResolvedInstructions
from mergecraft.agents.stream_budget import charge_review_stream_step
from mergecraft.config.settings import RepoInfo, RepoSettings, RunContextData
from mergecraft.review.pipeline import dispatch as pipeline_dispatch
from mergecraft.utils.run_bounds import BudgetTracker, RunBounds, resolve_run_bounds

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


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    reviewer: Any = None,
    bounds: RunBounds | None = None,
) -> main_mod.RunContext:
    tool_context = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    tracker = BudgetTracker(bounds or resolve_run_bounds(env={}))
    tool_context.budget_tracker = tracker
    run_ctx = run_ctx_for(tool_context)
    run_ctx.instructions = ResolvedInstructions(system="run start", user="review")
    run_ctx.resolved_model = _STREAMING
    run_ctx.budget_tracker = tracker
    reviewer = reviewer if reviewer is not None else _Reviewer()
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


# --------------------------------------------------------------------------- every attempt (#1586)


class _ScriptedReviewer:
    """Spends like the scripted attempt for whichever chain model it runs as."""

    name = "claude"

    def __init__(self, script: dict[str, ScriptedAttempt]) -> None:
        self.script = script
        self.models: list[str] = []

    async def install(self) -> None:
        return None

    async def run(self, ctx: Any) -> AgentResult:
        self.models.append(ctx.resolved_model)
        return self.script[ctx.resolved_model].run(ctx)


def _chain_through(monkeypatch: pytest.MonkeyPatch, attempts: list[str]) -> None:
    """Run every scripted attempt in order; the last one is the chain's answer."""

    async def _chain(*, run_once: Any, **_kwargs: Any) -> tuple[str, AgentResult]:
        results = [await run_once(slug) for slug in attempts]
        return attempts[-1], results[-1]

    monkeypatch.setattr(pipeline_dispatch, "run_with_model_chain", _chain)


@pytest.mark.parametrize("script", sorted(CHAIN_SCRIPTS))
async def test_every_chain_attempt_is_priced_listed_and_charged_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script: str
) -> None:
    first, second = CHAIN_SCRIPTS[script]
    models = (_AGGREGATE, _STREAMING) if not first.streamed else (_STREAMING, _AGGREGATE)
    install_chain_rates(monkeypatch, models)
    reviewer = _ScriptedReviewer(dict(zip(models, (first, second), strict=True)))
    run = _run(tmp_path, monkeypatch, reviewer=reviewer)
    run.use_model_chain = True
    _chain_through(monkeypatch, list(models))
    assert run.budget_tracker is not None
    assert run.tool_state is not None

    slug, result = await main_mod._run_agent_task_with_deadline(run)
    main_mod._promote_and_finalize_agent_result(run, slug, result)

    rows = run.tool_state.usage_entries
    costs = [expected_cost(first, position=0), expected_cost(second, position=1)]
    assert reviewer.models == list(models)
    assert [(row.input_tokens, row.output_tokens) for row in rows] == [
        (first.input_tokens, first.output_tokens),
        (second.input_tokens, second.output_tokens),
    ]
    assert [row.cost_usd for row in rows] == pytest.approx(costs)
    assert run.budget_tracker.tokens_used == first.tokens + second.tokens
    assert run.budget_tracker.cost_used == pytest.approx(sum(costs))
    assert run.budget_exhaustion is None
    # The winner is still the chain's answer and the model recorded as executed.
    assert slug == models[1]
    assert run.tool_state.model == models[1]
    assert result.usage is not None
    assert result.usage.cost_usd == pytest.approx(costs[1])


async def test_a_chain_stops_before_an_attempt_once_an_earlier_one_spent_the_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An attempt that exhausts the budget is charged; no further paid attempt opens."""
    first, second = CHAIN_SCRIPTS["aggregate-fails-then-stream-wins"]
    models = (_AGGREGATE, _STREAMING)
    install_chain_rates(monkeypatch, models)
    reviewer = _ScriptedReviewer(dict(zip(models, (first, second), strict=True)))
    bounds = replace(resolve_run_bounds(env={}), cost_budget_usd=0.1)
    run = _run(tmp_path, monkeypatch, reviewer=reviewer, bounds=bounds)
    run.use_model_chain = True
    _chain_through(monkeypatch, list(models))
    assert run.budget_tracker is not None
    assert run.tool_state is not None

    slug, result = await main_mod._run_agent_task_with_deadline(run)

    assert reviewer.models == [_AGGREGATE]
    assert slug == _AGGREGATE
    assert result.success is False
    assert len(run.tool_state.usage_entries) == 1
    assert run.budget_tracker.cost_used == pytest.approx(expected_cost(first, position=0))
    assert run.budget_exhaustion is not None
    assert run.budget_exhaustion.kind == "cost"
