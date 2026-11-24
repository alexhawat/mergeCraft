"""Server-side dispatches charge their usage to the run budget (#1559).

A secondary roster reviewer and a file-group reviewer each spend provider
tokens. ``_dispatch_reviewer`` used to drop ``AgentResult.usage`` on the floor:
no catalog price, no ``usage_entries`` row and no ``record_agent_usage`` call, so
``MERGECRAFT_COST_BUDGET_USD`` and the reported review cost under-counted every
dispatch.

The contract under test, in this order:

1. price the usage with ``apply_catalog_cost_to_usage(usage, model=<attempt model>)``;
2. append the priced usage to ``tool_state.usage_entries``;
3. charge it with ``record_agent_usage(tracker, priced, phase="reviewer_dispatch")``.

A reviewer that reports usage is charged whether it succeeded or not, and an
overrun surfaces as ``BudgetExhausted`` with a dispatch error that names the
budget.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from mergecraft.agents.registry import ResolvedAgentModel
from mergecraft.agents.shared import AgentResult, AgentRunContext, AgentUsage
from mergecraft.config.settings import load_repo_settings
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import (
    init_tool_state,
    primary_repo_state,
    record_reviewer_dispatch_run,
)
from mergecraft.review.file_group_fanout import plan_file_groups
from mergecraft.review.roster_execution import (
    run_file_group_reviewers,
    run_pending_roster_reviewers,
)
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.instructions import ResolvedInstructions
from mergecraft.utils.run_bounds import BudgetTracker, resolve_run_bounds
from tests.agents.conftest import make_agent_run_context
from tests.cli.support_agent_roster import write_config

_PAYLOAD: dict[str, Any] = {"event": {"trigger": "unknown"}}
_PRIMARY_MODEL = "anthropic/claude-sonnet"
_SECONDARY_MODEL = "openai/gpt-5.3-codex"
# The only curated slug: 0.15 USD/Mtok input, 0.50 USD/Mtok output, 0.03 cached.
_CURATED_MODEL = "paperinstruments/ultramarine-1-flash"
_MTOK = 1_000_000.0

#: A 300k-token reviewer that reported its own price.
_PRICED_USAGE = AgentUsage(
    agent="opencode",
    input_tokens=200_000,
    output_tokens=100_000,
    cost_usd=1.25,
)

#: The same token counts with no provider-reported price.
_UNPRICED_USAGE = AgentUsage(agent="opencode", input_tokens=200_000, output_tokens=100_000)


def _config(*, secondary_model: str = _SECONDARY_MODEL, extra: str = "") -> str:
    return (
        f"""
models:
  - {_PRIMARY_MODEL}
  - {secondary_model}
agents:
  reviewer:
    modelChain:
      - {_PRIMARY_MODEL}
  reviewer2:
    role: reviewer
    modelChain:
      - {secondary_model}
"""
        + extra
    )


def _fanout_block(**fields: object) -> str:
    lines = ["", "review:", "  fileGroupFanout:"]
    lines.extend(
        f"    {key}: {'true' if value is True else value}" for key, value in fields.items()
    )
    return "\n".join(lines) + "\n"


def _diff(file_count: int, lines_per_file: int) -> str:
    chunks: list[str] = []
    for index in range(file_count):
        path = f"src/pkg/mod_{index:02d}.py"
        added = "\n".join(f"+value_{index}_{line} = {line}" for line in range(lines_per_file))
        chunks.append(
            f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            f"@@ -0,0 +1,{lines_per_file} @@\n{added}\n"
        )
    return "".join(chunks)


_LARGE_DIFF = _diff(30, 30)


class _UsageAgent:
    """Reviewer runtime that returns one canned result for every dispatch.

    On a successful secondary dispatch it records its run, the way the roster
    submit block instructs a real reviewer to.
    """

    name = "opencode"

    def __init__(self, result: AgentResult, *, is_file_group: bool = False) -> None:
        self._result = result
        self._is_file_group = is_file_group
        self.calls = 0

    async def install(self) -> None:
        return None

    async def run(self, ctx: AgentRunContext) -> AgentResult:
        self.calls += 1
        if self._result.success and not self._is_file_group:
            record_reviewer_dispatch_run(
                ctx.tool_state,
                agent_id="reviewer2",
                findings=[],
                model_slug=ctx.resolved_model,
            )
        return self._result


def _patch_dispatch_seams(monkeypatch: pytest.MonkeyPatch, agent: Any) -> None:
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

    def _resolved(binding: Any, **kwargs: Any) -> ResolvedAgentModel:
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


class _Env:
    def __init__(
        self,
        *,
        root: Path,
        tool_state: Any,
        tool_context: ToolContext,
        settings: Any,
        base_ctx: AgentRunContext,
        tracker: BudgetTracker,
    ) -> None:
        self.root = root
        self.tool_state = tool_state
        self.tool_context = tool_context
        self.settings = settings
        self.base_ctx = base_ctx
        self.tracker = tracker


def _build_env(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    agent: Any,
    config: str | None = None,
    diff: str | None = None,
    tracker: BudgetTracker | None = None,
) -> _Env:
    root.mkdir(parents=True, exist_ok=True)
    write_config(root, config or _config())
    monkeypatch.chdir(root)
    scratch = root / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    tool_state = init_tool_state(owner="local", name="demo", dir=str(root))
    if diff is not None:
        diff_path = scratch / "pr.diff"
        diff_path.write_text(diff, encoding="utf-8")
        primary_repo_state(tool_state).diff_path = str(diff_path)
    budget = tracker or BudgetTracker(bounds=resolve_run_bounds(env={}))
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
        tmpdir=str(scratch),
        trust_tier="trusted",
        budget_tracker=budget,
    )
    settings = load_repo_settings(root=root)
    template = make_agent_run_context(scratch, resolved_model=_PRIMARY_MODEL)
    base_ctx = AgentRunContext(
        payload=template.payload,
        mcp_server_url=tool_context.mcp_server_url,
        mcp_auth_token="",
        tmpdir=str(scratch),
        subagent_denied_tools=(),
        instructions=template.instructions,
        tool_state=tool_state,
        api_token="",
        resolved_model=_PRIMARY_MODEL,
    )
    _patch_dispatch_seams(monkeypatch, agent)
    return _Env(
        root=root,
        tool_state=tool_state,
        tool_context=tool_context,
        settings=settings,
        base_ctx=base_ctx,
        tracker=budget,
    )


async def _run_roster(env: _Env) -> Any:
    return await run_pending_roster_reviewers(
        tool_context=env.tool_context,
        base_run_ctx=env.base_ctx,
        settings=env.settings,
        payload=_PAYLOAD,
        repo_root=env.root,
        per_reviewer_timeout_s=30.0,
    )


async def _run_fanout(env: _Env) -> Any:
    return await run_file_group_reviewers(
        tool_context=env.tool_context,
        base_run_ctx=env.base_ctx,
        settings=env.settings,
        payload=_PAYLOAD,
        repo_root=env.root,
    )


# --------------------------------------------------------------------------- happy path


@pytest.mark.xfail(reason="green after W2", strict=True)
async def test_secondary_reviewer_usage_reaches_usage_entries_and_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#1559 — a 300k-token secondary reviewer is listed and charged exactly once."""
    agent = _UsageAgent(AgentResult(success=True, output="ok", usage=_PRICED_USAGE))
    env = _build_env(tmp_path, monkeypatch, agent=agent)

    summary = await _run_roster(env)

    assert summary.hard_error is None
    assert len(env.tool_state.usage_entries) == 1
    entry = env.tool_state.usage_entries[0]
    assert entry.input_tokens == _PRICED_USAGE.input_tokens
    assert entry.output_tokens == _PRICED_USAGE.output_tokens
    assert entry.cost_usd == pytest.approx(_PRICED_USAGE.cost_usd)
    assert env.tracker.tokens_used == (_PRICED_USAGE.input_tokens + _PRICED_USAGE.output_tokens)
    assert env.tracker.cost_used == pytest.approx(_PRICED_USAGE.cost_usd)
    assert env.tracker.phase_totals["reviewer_dispatch"] == (
        _PRICED_USAGE.input_tokens + _PRICED_USAGE.output_tokens
    )


@pytest.mark.xfail(reason="green after W2", strict=True)
async def test_file_group_reviewer_usage_is_charged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#1559 — every file-group dispatch is charged, one entry per group."""
    groups = plan_file_groups(_LARGE_DIFF, max_groups=2)
    assert len(groups.groups) == 2
    agent = _UsageAgent(AgentResult(success=True, output="ok", usage=_PRICED_USAGE))
    env = _build_env(
        tmp_path,
        monkeypatch,
        agent=agent,
        config=_config(extra=_fanout_block(enabled=True, maxGroups=2)),
        diff=_LARGE_DIFF,
    )

    summary = await _run_fanout(env)

    assert summary.degraded is False
    assert agent.calls == len(groups.groups) == 2
    assert len(env.tool_state.usage_entries) == 2
    assert all(
        entry.cost_usd == pytest.approx(_PRICED_USAGE.cost_usd)
        for entry in env.tool_state.usage_entries
    )
    tokens = _PRICED_USAGE.input_tokens + _PRICED_USAGE.output_tokens
    assert env.tracker.tokens_used == tokens * 2
    assert env.tracker.cost_used == pytest.approx(_PRICED_USAGE.cost_usd * 2)


@pytest.mark.xfail(reason="green after W2", strict=True)
async def test_failed_reviewer_with_usage_is_still_charged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reviewer that failed after spending is recorded as failed *and* charged."""
    agent = _UsageAgent(
        AgentResult(success=False, error="provider 500", usage=_PRICED_USAGE),
    )
    env = _build_env(tmp_path, monkeypatch, agent=agent)

    summary = await _run_roster(env)

    assert summary.hard_error is not None
    assert "provider 500" in env.tool_state.reviewer_dispatch_errors["reviewer2"]
    assert len(env.tool_state.usage_entries) == 1
    assert env.tracker.cost_used == pytest.approx(_PRICED_USAGE.cost_usd)
    assert env.tracker.tokens_used == (_PRICED_USAGE.input_tokens + _PRICED_USAGE.output_tokens)


@pytest.mark.xfail(reason="green after W2", strict=True)
async def test_usage_without_cost_is_priced_with_the_attempt_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider that omits ``cost_usd`` gets the binding model's catalog price."""
    agent = _UsageAgent(AgentResult(success=True, output="ok", usage=_UNPRICED_USAGE))
    env = _build_env(
        tmp_path,
        monkeypatch,
        agent=agent,
        config=_config(secondary_model=_CURATED_MODEL),
    )

    await _run_roster(env)

    assert len(env.tool_state.usage_entries) == 1
    entry = env.tool_state.usage_entries[0]
    expected = (_UNPRICED_USAGE.input_tokens * 0.15 + _UNPRICED_USAGE.output_tokens * 0.50) / _MTOK
    assert entry.cost_usd == pytest.approx(expected)
    assert env.tracker.cost_used == pytest.approx(expected)


@pytest.mark.xfail(reason="green after W2", strict=True)
async def test_secondary_reviewer_overrun_raises_budget_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An overrun is not swallowed as "this reviewer failed": it reaches the run."""
    from mergecraft.utils.run_bounds import BudgetExhausted

    agent = _UsageAgent(AgentResult(success=True, output="ok", usage=_PRICED_USAGE))
    tracker = BudgetTracker(bounds=replace(resolve_run_bounds(env={}), cost_budget_usd=0.001))
    env = _build_env(tmp_path, monkeypatch, agent=agent, tracker=tracker)

    with pytest.raises(BudgetExhausted):
        await _run_roster(env)

    reason = env.tool_state.reviewer_dispatch_errors["reviewer2"]
    assert "budget" in reason.lower()
    assert tracker.last_exhausted is not None


# --------------------------------------------------------------------------- guards


async def test_reviewer_without_usage_charges_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard: a reviewer that reports no usage adds no entry and no charge."""
    agent = _UsageAgent(AgentResult(success=True, output="ok"))
    env = _build_env(tmp_path, monkeypatch, agent=agent)

    summary = await _run_roster(env)

    assert summary.hard_error is None
    assert env.tool_state.usage_entries == []
    assert env.tracker.tokens_used == 0
    assert env.tracker.cost_used == 0.0


async def test_primary_usage_entries_are_untouched_by_roster_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard: the primary's already-priced entry survives roster dispatch unchanged."""
    primary_usage = AgentUsage(
        agent="opencode",
        input_tokens=1000,
        output_tokens=500,
        cost_usd=0.5,
    )
    agent = _UsageAgent(AgentResult(success=True, output="ok"))
    env = _build_env(tmp_path, monkeypatch, agent=agent)
    env.tool_state.usage_entries.append(primary_usage)

    await _run_roster(env)

    assert env.tool_state.usage_entries == [primary_usage]
    assert env.tracker.cost_used == 0.0
