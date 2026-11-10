"""Secondary-reviewer requirement policy and per-reviewer deadline budget.

``review.rosterRequired`` decides which secondary reviewers a run needs:
``all`` (default) every one, ``marked`` only those with ``required: true``. A
required reviewer that fails is the roster's hard error; any other failure is a
degradation note. Each secondary runs under its own deadline budget.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.agents.registry import ResolvedAgentModel
from mergecraft.agents.shared import AgentResult, ResolvedInstructions
from mergecraft.config.settings import RepoSettings, load_repo_settings
from mergecraft.review.roster_execution import run_pending_roster_reviewers
from tests.cli.support_agent_roster import DEFAULT_MODELS_YAML, write_config
from tests.support.publication import RecordingReviewGitHub, publication_ctx, run_ctx_for

if TYPE_CHECKING:
    from pathlib import Path

_ROSTER = """
agents:
  reviewer:
    modelChain:
      - anthropic/claude-sonnet
  reviewer2:
    role: reviewer
    modelChain:
      - openai/gpt-5.3-codex
{required}
"""


class _TimesOut:
    name = "opencode"

    async def install(self) -> None:
        return None

    async def run(self, ctx: Any) -> AgentResult:
        raise TimeoutError


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, config: str) -> Any:
    write_config(tmp_path, DEFAULT_MODELS_YAML + config)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.resolve_runtime_agent", lambda **_: _TimesOut()
    )
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.credential_status_for_slug",
        lambda *a, **k: type("S", (), {"available": True})(),
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
    return ctx, settings


async def _dispatch(ctx: Any, settings: RepoSettings, tmp_path: Path) -> Any:
    run_start = ResolvedInstructions(system="run-start", user="review")
    return await run_pending_roster_reviewers(
        tool_context=ctx,
        base_run_ctx=run_ctx_for(ctx),
        settings=settings,
        payload={"event": {"trigger": "unknown"}},
        repo_root=tmp_path,
        instructions_for={"opencode": run_start}.get,
    )


async def test_by_default_a_secondary_timeout_is_the_roster_hard_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, settings = _setup(tmp_path, monkeypatch, config=_ROSTER.format(required=""))

    summary = await _dispatch(ctx, settings, tmp_path)

    assert summary.hard_error is not None
    assert "reviewer2" in summary.hard_error
    assert "timed out" in summary.hard_error


async def test_marked_policy_records_an_unmarked_failure_as_degraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = "review:\n  rosterRequired: marked\n" + _ROSTER.format(required="")
    ctx, settings = _setup(tmp_path, monkeypatch, config=config)

    summary = await _dispatch(ctx, settings, tmp_path)

    assert summary.hard_error is None
    assert "reviewer2" in ctx.tool_state.reviewer_dispatch_errors


async def test_marked_policy_still_requires_a_reviewer_marked_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = "review:\n  rosterRequired: marked\n" + _ROSTER.format(required="    required: true")
    ctx, settings = _setup(tmp_path, monkeypatch, config=config)

    summary = await _dispatch(ctx, settings, tmp_path)

    assert summary.hard_error is not None


def test_an_unknown_roster_policy_is_a_configuration_error() -> None:
    with pytest.raises(ValueError, match="rosterRequired"):
        RepoSettings.model_validate({"review": {"rosterRequired": "some"}})


async def test_a_primary_that_used_its_deadline_leaves_secondaries_their_own_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import mergecraft.main as main_mod
    import mergecraft.review.roster_execution as roster_mod

    ctx, settings = _setup(tmp_path, monkeypatch, config=_ROSTER.format(required=""))
    budgets: list[float | None] = []

    async def _capture(**kwargs: Any) -> Any:
        budgets.append(kwargs["timeout_s"])
        return roster_mod._SecondaryOutcome(None)

    monkeypatch.setattr(roster_mod, "_run_one_secondary_reviewer", _capture)
    ctx.tool_state.selected_mode = "Review"
    run = main_mod.RunContext(
        settings=settings,
        tool_context=ctx,
        tool_state=ctx.tool_state,
        run_ctx=run_ctx_for(ctx),
        payload={"event": {"trigger": "unknown"}},
        # The primary consumed its whole deadline.
        agent_deadline_monotonic=time.monotonic() - 5.0,
    )

    await main_mod._run_server_roster_reviewers_if_needed(run)

    assert budgets
    assert budgets[0] is not None
    assert budgets[0] >= 60.0
