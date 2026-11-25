"""A spent run budget stops server-side dispatch and ends the run inconclusive.

#1584: the primary's final usage charge can exhaust the run's cost budget. The
Action used to go straight on into the secondary roster, so a configured
secondary started a paid call after the run was already over budget.

#1585: a secondary whose own usage crossed the ceiling re-raised
``BudgetExhausted``. It reached the Action's outer catch-all, which classified
it as an infrastructure fault rather than the inconclusive budget stop the
outcome resolver maps it to.

Both run the Action's own sequence (``_dispatch_agent_with_deadline``, then
``_run_server_roster_reviewers_if_needed``, then ``_finalize``) with one
configured secondary and the file-group fan-out left off.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest
from tests.cli.support_agent_roster import write_config
from tests.review.test_roster_usage_charging import _config, _patch_dispatch_seams, _UsageAgent
from tests.support.publication import (
    RecordingReviewGitHub,
    publication_ctx,
    run_ctx_for,
    submit_verdict,
)

import mergecraft.main as main_mod
from mergecraft.action import review_finalize
from mergecraft.agents.post_run import finalize_agent_result
from mergecraft.agents.shared import INFRA_REASON_KEY, AgentResult, AgentUsage
from mergecraft.config.settings import RepoInfo, RunContextData, load_repo_settings
from mergecraft.review.roster_execution import apply_roster_failure
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.instructions import ResolvedInstructions
from mergecraft.utils.run_bounds import BudgetExhausted, BudgetTracker, resolve_run_bounds

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.mcp.context import ToolContext

_COST_BUDGET_USD = 1.0
_OVER = AgentUsage(agent="claude", input_tokens=200_000, output_tokens=100_000, cost_usd=1.25)
_UNDER = AgentUsage(agent="claude", input_tokens=20_000, output_tokens=10_000, cost_usd=0.2)


class _Primary:
    """A primary reviewer that submits its verdict and reports its usage on completion."""

    name = "claude"

    def __init__(self, tool_context: ToolContext, usage: AgentUsage) -> None:
        self.tool_context = tool_context
        self.usage = usage
        self.calls = 0

    async def install(self) -> None:
        return None

    async def run(self, ctx: Any) -> AgentResult:
        self.calls += 1
        await submit_verdict(self.tool_context, "approve", [])
        result = await finalize_agent_result(
            run_ctx_for(self.tool_context), AgentResult(success=True, output="ok")
        )
        return replace(result, usage=self.usage)


class _Run:
    def __init__(self, run: main_mod.RunContext, primary: _Primary, secondary: Any) -> None:
        self.ctx = run
        self.primary = primary
        self.secondary = secondary
        self.published: list[dict[str, Any]] = []


def _action_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    primary_usage: AgentUsage,
    secondary_result: AgentResult,
) -> _Run:
    write_config(tmp_path, _config())
    monkeypatch.chdir(tmp_path)
    tool_context = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    tracker = BudgetTracker(
        bounds=replace(resolve_run_bounds(env={}), cost_budget_usd=_COST_BUDGET_USD)
    )
    tool_context.budget_tracker = tracker
    run_ctx = run_ctx_for(tool_context)
    run_ctx.instructions = ResolvedInstructions(system="run start", user="review")
    run_ctx.budget_tracker = tracker
    secondary = _UsageAgent(secondary_result)
    _patch_dispatch_seams(monkeypatch, secondary)
    primary = _Primary(tool_context, primary_usage)
    ctx = main_mod.RunContext(
        settings=load_repo_settings(root=tmp_path),
        tool_context=tool_context,
        tool_state=tool_context.tool_state,
        run_ctx=run_ctx,
        tmpdir=tool_context.tmpdir,
        budget_tracker=tracker,
        agent=primary,  # type: ignore[arg-type]  # — a duck-typed fake driver
        agent_id="claude",
        payload={"event": {"trigger": "pull_request"}},
        run_start_instructions={secondary.name: run_ctx.instructions},
    )
    ctx.run_context = RunContextData(
        repo=RepoInfo(owner="acme", name="demo"), repoSettings=ctx.settings
    )
    out = _Run(ctx, primary, secondary)

    async def _record(_ctx: Any, **kwargs: Any) -> None:
        out.published.append(kwargs)

    monkeypatch.setattr(main_mod, "_publish", _record)
    monkeypatch.setattr(review_finalize, "_scan_sinks_after_run", lambda *_a, **_k: None)
    return out


async def _review_and_finalize(run: _Run) -> main_mod.MainResult:
    """The Action's review-stage tail (``main._run_review_after_analyze``), then publish."""
    result = await main_mod._dispatch_agent_with_deadline(run.ctx)
    roster = await main_mod._run_server_roster_reviewers_if_needed(run.ctx)
    return await main_mod._finalize(run.ctx, apply_roster_failure(result, roster))


def _assert_inconclusive_budget_stop(run: _Run, outcome: main_mod.MainResult) -> None:
    assert outcome.outcome is RunOutcome.inconclusive
    assert "cost budget exhausted" in (outcome.error or "")
    (published,) = run.published
    assert published["outcome"] is RunOutcome.inconclusive
    assert "cost budget exhausted" in (published["failure_reason"] or "")


async def test_a_primary_overrun_skips_the_secondary_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _action_run(
        tmp_path,
        monkeypatch,
        primary_usage=_OVER,
        secondary_result=AgentResult(success=True, output="ok", usage=_UNDER),
    )

    outcome = await _review_and_finalize(run)

    assert run.primary.calls == 1
    assert run.secondary.calls == 0
    assert run.ctx.budget_exhaustion is not None
    assert run.ctx.budget_exhaustion.kind == "cost"
    # The primary's final charge is listed and charged exactly once.
    assert run.ctx.tool_state is not None
    assert run.ctx.budget_tracker is not None
    assert len(run.ctx.tool_state.usage_entries) == 1
    assert run.ctx.budget_tracker.cost_used == pytest.approx(_OVER.cost_usd)
    _assert_inconclusive_budget_stop(run, outcome)


async def test_below_the_ceiling_the_secondary_still_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _action_run(
        tmp_path,
        monkeypatch,
        primary_usage=_UNDER,
        secondary_result=AgentResult(success=True, output="ok", usage=_UNDER),
    )

    result = await main_mod._dispatch_agent_with_deadline(run.ctx)
    roster = await main_mod._run_server_roster_reviewers_if_needed(run.ctx)

    assert run.secondary.calls == 1
    assert roster is not None
    assert roster.hard_error is None
    assert roster.dispatched_agent_ids == ("reviewer2",)
    assert run.ctx.budget_exhaustion is None
    assert apply_roster_failure(result, roster) is result
    assert run.ctx.budget_tracker is not None
    assert run.ctx.budget_tracker.cost_used == pytest.approx(2 * (_UNDER.cost_usd or 0.0))


async def test_a_secondary_overrun_is_an_inconclusive_budget_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _action_run(
        tmp_path,
        monkeypatch,
        primary_usage=_UNDER,
        secondary_result=AgentResult(success=True, output="ok", usage=_OVER),
    )

    outcome = await _review_and_finalize(run)

    assert run.secondary.calls == 1
    assert run.ctx.budget_exhaustion is not None
    assert run.ctx.budget_exhaustion.kind == "cost"
    # The secondary's actual usage is retained once, beside the primary's.
    assert run.ctx.tool_state is not None
    assert run.ctx.budget_tracker is not None
    assert [row.cost_usd for row in run.ctx.tool_state.usage_entries] == [
        _UNDER.cost_usd,
        _OVER.cost_usd,
    ]
    assert run.ctx.budget_tracker.cost_used == pytest.approx(
        (_UNDER.cost_usd or 0.0) + (_OVER.cost_usd or 0.0)
    )
    assert outcome.outcome is not RunOutcome.infra_error
    _assert_inconclusive_budget_stop(run, outcome)


async def test_a_secondary_infrastructure_failure_keeps_its_classification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: a genuine provider infrastructure fault is still ``infra_error``."""
    run = _action_run(
        tmp_path,
        monkeypatch,
        primary_usage=_UNDER,
        secondary_result=AgentResult(
            success=False,
            error="codex login expired",
            metadata={INFRA_REASON_KEY: "codex subscription login expired"},
        ),
    )

    outcome = await _review_and_finalize(run)

    assert run.ctx.budget_exhaustion is None
    assert outcome.outcome is RunOutcome.infra_error


def test_the_outer_classifier_maps_a_budget_stop_to_inconclusive() -> None:
    assert (
        main_mod._classify_error_outcome(BudgetExhausted("cost", "cost budget exhausted"))
        is RunOutcome.inconclusive
    )
    assert main_mod._classify_error_outcome(RuntimeError("socket closed")) is (
        RunOutcome.infra_error
    )
