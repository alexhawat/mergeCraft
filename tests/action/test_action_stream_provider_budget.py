"""Action dispatch keeps provider budgets advisory and surfaces stream ceiling stops."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.publication import (
    RecordingReviewGitHub,
    publication_ctx,
    run_ctx_for,
    submit_verdict,
)

import mergecraft.main as main_mod
from mergecraft.action import review_finalize
from mergecraft.agents.post_run import finalize_agent_result
from mergecraft.agents.shared import AgentResult
from mergecraft.config.settings import RepoSettings
from mergecraft.review.pipeline.dispatch import resolve_review_provider_budget
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.run_bounds import BudgetExhausted, BudgetTracker, resolve_run_bounds


def test_action_dispatch_provider_budget_is_advisory() -> None:
    """MC-bd4d62: enforced provider caps must not wrap the whole model chain."""
    budget = resolve_review_provider_budget(model="opencode-go/test", max_tokens=2_200_000)
    assert budget.advisory is True


@pytest.mark.asyncio
async def test_mid_stream_ceiling_stop_never_publishes_clean_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stream budget halt is inconclusive and withholds approval (reduced coverage)."""
    github = RecordingReviewGitHub()
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted")
    ctx.pr_approve_enabled = True
    ctx.authority_trust = "trusted"
    await submit_verdict(ctx, "approve", [])

    tracker = BudgetTracker(resolve_run_bounds(env={}))
    tracker.last_exhausted = BudgetExhausted(
        "token",
        "token budget exhausted during review: single increment over ceiling",
    )
    agent = AgentResult(
        success=False,
        error="token budget exhausted during review: single increment over ceiling",
        metadata={"retryable": False, "budget_exhausted": True},
    )
    driver = await finalize_agent_result(run_ctx_for(ctx), agent)

    async def _record(_ctx: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(main_mod, "_publish", _record)
    monkeypatch.setattr(review_finalize, "_scan_sinks_after_run", lambda *_a, **_k: None)
    monkeypatch.setattr(
        review_finalize,
        "_coverage_gate_reason",
        lambda *_a, **_k: "changed-line coverage incomplete after budget stop",
    )

    run = main_mod.RunContext(
        settings=RepoSettings(),
        tool_context=ctx,
        tool_state=ctx.tool_state,
        run_ctx=run_ctx_for(ctx),
        tmpdir=ctx.tmpdir,
        budget_tracker=tracker,
    )
    outcome = await main_mod._finalize(run, driver)

    assert outcome.outcome is RunOutcome.inconclusive
    assert outcome.outcome is not RunOutcome.passed
    assert "APPROVE" not in [str(p.get("event")) for p in github.review_payloads]
    assert outcome.error is not None
    assert "token budget" in outcome.error.lower()
