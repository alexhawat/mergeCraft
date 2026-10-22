"""Server-side secondary reviewer dispatch (D15)."""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.agents.registry import ResolvedAgentModel
from mergecraft.agents.shared import AgentResult, AgentRunContext
from mergecraft.config.settings import load_repo_settings
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state, record_reviewer_dispatch_run
from mergecraft.review.roster_execution import (
    roster_dispatch_gaps,
    run_pending_roster_reviewers,
)
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.instructions import ResolvedInstructions
from tests.agents.conftest import make_agent_run_context
from tests.cli.support_agent_roster import two_reviewer_config, write_config


class _FakeAgent:
    name = "opencode"

    def __init__(self) -> None:
        self.models: list[str] = []

    async def install(self) -> None:
        return None

    async def run(self, ctx: AgentRunContext) -> AgentResult:
        self.models.append(ctx.resolved_model or "")
        record_reviewer_dispatch_run(
            ctx.tool_state,
            agent_id="reviewer2",
            findings=[{"path": "a.py", "body": "from secondary", "severity": "Minor", "line": 1}],
            model_slug=ctx.resolved_model,
        )
        return AgentResult(success=True, output="ok")


@pytest.mark.asyncio
async def test_run_pending_roster_reviewers_dispatches_secondary(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_config(tmp_path, two_reviewer_config())
    monkeypatch.chdir(tmp_path)
    tool_state = init_tool_state(owner="local", name="demo", dir=str(tmp_path))
    tool_context = ToolContext(
        agent_id="opencode",
        repo=RepoIdentity(owner="local", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="unknown"), shell="disabled"),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=(),
        tool_state=tool_state,
        mcp_server_url="http://127.0.0.1:9/mcp/reviewer",
        tmpdir=str(tmp_path / "scratch"),
        trust_tier="trusted",
    )
    settings = load_repo_settings(root=tmp_path)
    fake = _FakeAgent()
    base_ctx = make_agent_run_context(
        tmp_path / "scratch", resolved_model="anthropic/claude-sonnet"
    )
    base_ctx = AgentRunContext(
        payload=base_ctx.payload,
        mcp_server_url=tool_context.mcp_server_url,
        mcp_auth_token="",
        tmpdir=str(tmp_path / "scratch"),
        subagent_denied_tools=(),
        instructions=base_ctx.instructions,
        tool_state=tool_state,
        api_token="",
        resolved_model="anthropic/claude-sonnet",
    )

    monkeypatch.setattr(
        "mergecraft.review.roster_execution.resolve_runtime_agent",
        lambda **kwargs: fake,
    )
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.credential_status_for_slug",
        lambda *args, **kwargs: type("S", (), {"available": True})(),
    )
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.resolve_model",
        lambda slug, respect_env_override=False: slug,
    )

    def _resolved(binding, **kwargs):
        slug = binding.model_chain[0] if binding.model_chain else "mock/model"
        return ResolvedAgentModel(
            requested_model=slug,
            executed_model=slug,
            recorded_model=slug,
            dispatched_model=slug,
        )

    monkeypatch.setattr(
        "mergecraft.agents.registry.resolve_agent_model",
        _resolved,
    )
    monkeypatch.setattr(
        "mergecraft.utils.instructions.resolve_instructions",
        lambda **kwargs: ResolvedInstructions(system="test", user="review"),
    )
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.subagent_denied_tool_names",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.verifier_denied_tool_names",
        lambda *args, **kwargs: [],
    )

    summary = await run_pending_roster_reviewers(
        tool_context=tool_context,
        base_run_ctx=base_ctx,
        settings=settings,
        payload={"event": {"trigger": "unknown"}},
        repo_root=tmp_path,
        per_reviewer_timeout_s=30.0,
    )
    assert summary.hard_error is None
    assert "reviewer2" in {run.agent_id for run in tool_state.reviewer_dispatch_runs}
    assert fake.models


def test_roster_dispatch_gaps_detects_missing_secondary(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(tmp_path, two_reviewer_config())
    monkeypatch.chdir(tmp_path)
    from mergecraft.agents.registry import load_registry

    registry = load_registry(settings=load_repo_settings(root=tmp_path), repo_root=tmp_path)
    tool_state = init_tool_state(owner="local", name="demo", dir=str(tmp_path))
    gaps = roster_dispatch_gaps(registry, tool_state)
    assert "reviewer2" in gaps


class _FailingSecondaryAgent:
    """A secondary that returns one canned result, the way a dead login does."""

    name = "codex"

    def __init__(self, result: AgentResult) -> None:
        self._result = result

    async def install(self) -> None:
        return None

    async def run(self, ctx: AgentRunContext) -> AgentResult:
        return self._result


async def _dispatch_one_secondary(tmp_path, monkeypatch: pytest.MonkeyPatch, agent: Any):
    """Run the roster dispatch with *agent* standing in for the secondary reviewer."""
    write_config(tmp_path, two_reviewer_config())
    monkeypatch.chdir(tmp_path)
    tool_state = init_tool_state(owner="local", name="demo", dir=str(tmp_path))
    tool_context = ToolContext(
        agent_id="opencode",
        repo=RepoIdentity(owner="local", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="unknown"), shell="disabled"),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=(),
        tool_state=tool_state,
        mcp_server_url="http://127.0.0.1:9/mcp/reviewer",
        tmpdir=str(tmp_path / "scratch"),
        trust_tier="trusted",
    )
    settings = load_repo_settings(root=tmp_path)
    base_ctx = make_agent_run_context(tmp_path / "scratch", resolved_model="codex/gpt-5.6")
    base_ctx = AgentRunContext(
        payload=base_ctx.payload,
        mcp_server_url=tool_context.mcp_server_url,
        mcp_auth_token="",
        tmpdir=str(tmp_path / "scratch"),
        subagent_denied_tools=(),
        instructions=base_ctx.instructions,
        tool_state=tool_state,
        api_token="",
        resolved_model="codex/gpt-5.6",
    )
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.resolve_runtime_agent",
        lambda **kwargs: agent,
    )
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.credential_status_for_slug",
        lambda *args, **kwargs: type("S", (), {"available": True})(),
    )
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.resolve_model",
        lambda slug, respect_env_override=False: slug,
    )

    def _resolved(binding, **kwargs):
        slug = binding.model_chain[0] if binding.model_chain else "mock/model"
        return ResolvedAgentModel(
            requested_model=slug,
            executed_model=slug,
            recorded_model=slug,
            dispatched_model=slug,
        )

    monkeypatch.setattr("mergecraft.agents.registry.resolve_agent_model", _resolved)
    monkeypatch.setattr(
        "mergecraft.utils.instructions.resolve_instructions",
        lambda **kwargs: ResolvedInstructions(system="test", user="review"),
    )
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.subagent_denied_tool_names",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.verifier_denied_tool_names",
        lambda *args, **kwargs: [],
    )
    summary = await run_pending_roster_reviewers(
        tool_context=tool_context,
        base_run_ctx=base_ctx,
        settings=settings,
        payload={"event": {"trigger": "unknown"}},
        repo_root=tmp_path,
        per_reviewer_timeout_s=30.0,
    )
    return summary, tool_state


@pytest.mark.asyncio
async def test_a_secondary_infra_failure_carries_its_named_reason(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An expired login on a *secondary* reviewer is infrastructure, not a failed review."""
    from mergecraft.agents.shared import INFRA_REASON_KEY

    named_reason = (
        "reviewer credential expired — re-authenticate "
        "(mergecraft auth codex, then gh secret set CODEX_AUTH_JSON)"
    )
    summary, _ = await _dispatch_one_secondary(
        tmp_path,
        monkeypatch,
        _FailingSecondaryAgent(
            AgentResult(
                success=False,
                error=named_reason,
                metadata={INFRA_REASON_KEY: "reviewer_credential_expired"},
            )
        ),
    )

    assert summary.hard_error
    assert named_reason in summary.hard_error
    assert summary.infra_reason == "reviewer_credential_expired"


def test_apply_roster_failure_makes_the_run_an_infra_error() -> None:
    """The reason travels from the secondary's result to the run's outcome (D15)."""
    from mergecraft.agents.shared import INFRA_REASON_KEY
    from mergecraft.main_outcome import _classify_outcome
    from mergecraft.review.roster_execution import RosterExecutionSummary, apply_roster_failure
    from mergecraft.run_outcome import RunOutcome

    primary = AgentResult(success=True, output="review text", metadata={"retryable": True})
    summary = RosterExecutionSummary(
        hard_error="secondary reviewer dispatch incomplete",
        dispatched_agent_ids=(),
        infra_reason="reviewer_credential_expired",
    )

    merged = apply_roster_failure(primary, summary)

    assert merged.success is False
    assert merged.error == "secondary reviewer dispatch incomplete"
    assert merged.metadata[INFRA_REASON_KEY] == "reviewer_credential_expired"
    # The primary's own metadata survives the fold.
    assert merged.metadata["retryable"] is True

    outcome, reason = _classify_outcome(
        result=merged,
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
    )

    assert outcome is RunOutcome.infra_error
    assert reason == "secondary reviewer dispatch incomplete"


def test_apply_roster_failure_leaves_a_clean_run_alone() -> None:
    """No roster failure, no rewrite — including a summary that was never produced."""
    from mergecraft.review.roster_execution import RosterExecutionSummary, apply_roster_failure

    primary = AgentResult(success=True, output="review text")
    assert apply_roster_failure(primary, None) is primary
    assert apply_roster_failure(primary, RosterExecutionSummary(None, ())) is primary
