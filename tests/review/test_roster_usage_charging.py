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

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from mergecraft.agents import cli_runner
from mergecraft.agents import opencode as oc
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
from mergecraft.utils.run_bounds import (
    BudgetExhausted,
    BudgetTracker,
    StreamCharges,
    resolve_run_bounds,
)
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
        modes=[],
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
        budget_tracker=budget,
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
    assert env.tracker.cost_used == pytest.approx((_PRICED_USAGE.cost_usd or 0.0) * 2)


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


async def test_secondary_reviewer_overrun_raises_budget_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An overrun is not swallowed as "this reviewer failed": it reaches the run."""
    agent = _UsageAgent(AgentResult(success=True, output="ok", usage=_PRICED_USAGE))
    tracker = BudgetTracker(bounds=replace(resolve_run_bounds(env={}), cost_budget_usd=0.001))
    env = _build_env(tmp_path, monkeypatch, agent=agent, tracker=tracker)

    with pytest.raises(BudgetExhausted):
        await _run_roster(env)

    reason = env.tool_state.reviewer_dispatch_errors["reviewer2"]
    assert "budget" in reason.lower()
    assert tracker.last_exhausted is not None


# --------------------------------------------------------------------------- stream residue


async def test_secondary_charge_is_not_reduced_by_the_primary_streamed_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#1559 — a previous dispatch's incremental charges must not shrink this one.

    The roster dispatches from the primary's run context, whose stream total is
    the primary's own. The secondary's aggregate charge must still add the
    secondary's whole usage, or the budget under-counts it again.
    """
    agent = _UsageAgent(AgentResult(success=True, output="ok", usage=_PRICED_USAGE))
    env = _build_env(tmp_path, monkeypatch, agent=agent)
    # What the primary's stream guard charged incrementally before finalizing.
    env.base_ctx.stream_charges = StreamCharges(tokens=120_000, cost_usd=0.50)

    await _run_roster(env)

    assert env.tracker.tokens_used == (_PRICED_USAGE.input_tokens + _PRICED_USAGE.output_tokens)
    assert env.tracker.cost_used == pytest.approx(_PRICED_USAGE.cost_usd)


# --------------------------------------------------------------------------- concurrency

_STREAM_MODEL = "acme/streaming"
_PEER_MODEL = "acme/aggregate"
_CONCURRENT_CONFIG = f"""
models:
  - {_PRIMARY_MODEL}
  - {_STREAM_MODEL}
  - {_PEER_MODEL}
agents:
  reviewer:
    modelChain:
      - {_PRIMARY_MODEL}
  reviewer2:
    role: reviewer
    modelChain:
      - {_STREAM_MODEL}
  reviewer3:
    role: reviewer
    modelChain:
      - {_PEER_MODEL}
"""
#: What the streaming reviewer's two steps add up to.
_STREAMED_TOKENS = 120_000
_STREAMED_COST = 1.0
#: A peer that spent less than the stream did, reported once when it finished.
_PEER_USAGE = AgentUsage(agent="claude", input_tokens=90_000, output_tokens=10_000, cost_usd=0.9)


class _StreamProc:
    """An opencode CLI process that has already written two finished steps."""

    pid = 777_124
    returncode = 0

    def __init__(self) -> None:
        step = {
            "type": "step_finish",
            "sessionID": "s1",
            "part": {"tokens": {"input": 50_000, "output": 10_000}, "cost": 0.5},
        }
        self.stdout = [json.dumps(step) + "\n"] * 2
        self.stderr: list[str] = []

    def poll(self) -> int:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode


class _ConcurrentReviewers:
    """One streaming and one aggregate-only reviewer, in a fixed interleaving.

    The streaming one runs opencode's real stream loop against a canned process.
    ``stream_first`` picks whether it streams before or after its peer's dispatch
    starts; the peer always finishes after the stream and before the streamer.
    """

    name = "opencode"

    def __init__(self, *, stream_first: bool) -> None:
        self._stream_first = stream_first
        self._peer_started = asyncio.Event()
        self._streamed = asyncio.Event()
        self._peer_done = asyncio.Event()

    async def install(self) -> None:
        return None

    async def run(self, ctx: AgentRunContext) -> AgentResult:
        if ctx.resolved_model == _STREAM_MODEL:
            return await self._run_streaming(ctx)
        self._peer_started.set()
        await self._streamed.wait()
        self._record(ctx, "reviewer3")
        self._peer_done.set()
        return AgentResult(success=True, output="ok", usage=_PEER_USAGE)

    async def _run_streaming(self, ctx: AgentRunContext) -> AgentResult:
        if not self._stream_first:
            await self._peer_started.wait()
        result = oc._run_opencode_cli_streaming(cmd=["opencode"], ctx=ctx, env={}, session={})
        self._streamed.set()
        await self._peer_done.wait()
        self._record(ctx, "reviewer2")
        return result

    @staticmethod
    def _record(ctx: AgentRunContext, agent_id: str) -> None:
        record_reviewer_dispatch_run(
            ctx.tool_state, agent_id=agent_id, findings=[], model_slug=ctx.resolved_model
        )


def _concurrent_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    stream_first: bool,
    cost_budget_usd: float = 10.0,
) -> _Env:
    monkeypatch.setattr(cli_runner, "spawn_agent_cli", lambda cmd, **kwargs: _StreamProc())
    bounds = replace(resolve_run_bounds(env={}), cost_budget_usd=cost_budget_usd)
    return _build_env(
        tmp_path,
        monkeypatch,
        agent=_ConcurrentReviewers(stream_first=stream_first),
        config=_CONCURRENT_CONFIG,
        tracker=BudgetTracker(bounds=bounds),
    )


@pytest.mark.parametrize("stream_first", [True, False])
async def test_concurrent_reviewers_are_each_charged_their_whole_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stream_first: bool
) -> None:
    """#1559 — one reviewer's streamed steps never discount or recharge a peer's usage."""
    env = _concurrent_env(tmp_path, monkeypatch, stream_first=stream_first)

    summary = await _run_roster(env)

    assert summary.hard_error is None
    assert summary.dispatched_agent_ids == ("reviewer2", "reviewer3")
    assert env.tracker.tokens_used == _STREAMED_TOKENS + 100_000
    assert env.tracker.cost_used == pytest.approx(_STREAMED_COST + 0.9)


async def test_concurrent_reviewers_cannot_cross_the_cost_ceiling_unnoticed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each reviewer fits the ceiling alone; together they cross it and end the run."""
    env = _concurrent_env(tmp_path, monkeypatch, stream_first=False, cost_budget_usd=1.5)

    with pytest.raises(BudgetExhausted):
        await _run_roster(env)

    assert "budget" in env.tool_state.reviewer_dispatch_errors["reviewer3"].lower()


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


# --------------------------------------------------------------------------- shared budget halts the fan-out (#1583)

#: A group's usage that fits the default ceiling once the run has budget left.
_SMALL_USAGE = AgentUsage(agent="opencode", input_tokens=1_000, output_tokens=500, cost_usd=0.05)


def _fanout_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    agent: Any,
    concurrency: int = 1,
    tracker: BudgetTracker | None = None,
) -> _Env:
    return _build_env(
        tmp_path,
        monkeypatch,
        agent=agent,
        config=_config(
            extra=_fanout_block(enabled=True, maxGroups=3, concurrency=concurrency),
        ),
        diff=_LARGE_DIFF,
        tracker=tracker
        or BudgetTracker(bounds=replace(resolve_run_bounds(env={}), cost_budget_usd=1.0)),
    )


def _run_health_messages(env: _Env) -> list[str]:
    return [
        str(row.get("message"))
        for row in env.tool_state.agent_findings
        if isinstance(row, dict) and row.get("scope") == "run"
    ]


def _resolved_outcome(env: _Env) -> Any:
    from mergecraft.review.outcome_resolution import OutcomeInputs, resolve_run_outcome
    from mergecraft.review.pipeline.finalize import complete_outcome_inputs

    inputs = complete_outcome_inputs(
        OutcomeInputs(result=AgentResult(success=True, terminal_submission_received=True)),
        budget_tracker=env.tracker,
    )
    return resolve_run_outcome(inputs)


async def test_a_cost_overrun_stops_queued_groups_from_dispatching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three groups at concurrency one: the first one's overrun is the last paid call."""
    from mergecraft.run_outcome import RunOutcome

    assert len(plan_file_groups(_LARGE_DIFF, max_groups=3).groups) == 3
    agent = _UsageAgent(
        AgentResult(success=True, output="ok", usage=_PRICED_USAGE), is_file_group=True
    )
    env = _fanout_env(tmp_path, monkeypatch, agent=agent)

    with pytest.raises(BudgetExhausted) as exc_info:
        await _run_fanout(env)

    assert exc_info.value.kind == "cost"
    assert agent.calls == 1
    # The spend already observed is kept, listed once and charged once.
    assert len(env.tool_state.usage_entries) == 1
    assert env.tracker.cost_used == pytest.approx(_PRICED_USAGE.cost_usd)
    # No group reads as one that merely "produced no findings".
    assert _run_health_messages(env) == []
    errors = env.tool_state.reviewer_dispatch_errors
    assert "exceeded the run budget" in errors["file-group/group-1"]
    for skipped in ("file-group/group-2", "file-group/group-3"):
        assert errors[skipped].startswith("not dispatched: the run budget is exhausted")
    outcome, reason = _resolved_outcome(env)
    assert outcome is RunOutcome.inconclusive
    assert "cost budget exhausted" in (reason or "")


class _TwoWorkerAgent:
    """Two groups in flight: the first exhausts the budget while the second still runs.

    The second group returns only once the first group's usage charge has run,
    which is the charge that exhausts the budget.
    """

    name = "opencode"

    def __init__(self, first_charged: asyncio.Event) -> None:
        self.first_charged = first_charged
        self.started: list[int] = []
        self._second_started = asyncio.Event()

    async def install(self) -> None:
        return None

    async def run(self, ctx: AgentRunContext) -> AgentResult:
        index = len(self.started)
        self.started.append(index)
        if index == 0:
            await asyncio.wait_for(self._second_started.wait(), timeout=10)
            return AgentResult(success=True, output="ok", usage=_PRICED_USAGE)
        self._second_started.set()
        await asyncio.wait_for(self.first_charged.wait(), timeout=10)
        return AgentResult(success=True, output="ok", usage=_SMALL_USAGE)


async def test_queued_work_never_starts_after_exhaustion_with_two_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The in-flight peer finishes and is charged; the queued third group never starts."""
    from mergecraft.review import roster_execution

    charged = asyncio.Event()
    real_charge = roster_execution.charge_reviewer_usage

    def _charge(**kwargs: Any) -> Any:
        try:
            return real_charge(**kwargs)
        finally:
            charged.set()

    monkeypatch.setattr(roster_execution, "charge_reviewer_usage", _charge)
    tracker = BudgetTracker(bounds=replace(resolve_run_bounds(env={}), cost_budget_usd=1.0))
    agent = _TwoWorkerAgent(charged)
    env = _fanout_env(tmp_path, monkeypatch, agent=agent, concurrency=2, tracker=tracker)

    with pytest.raises(BudgetExhausted):
        await _run_fanout(env)

    assert agent.started == [0, 1]
    assert len(env.tool_state.usage_entries) == 2
    assert tracker.cost_used == pytest.approx(
        (_PRICED_USAGE.cost_usd or 0.0) + (_SMALL_USAGE.cost_usd or 0.0)
    )
    assert _run_health_messages(env) == []
    assert env.tool_state.reviewer_dispatch_errors["file-group/group-3"].startswith(
        "not dispatched"
    )


async def test_an_exhaustion_recorded_outside_a_group_also_stops_queued_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tool-call overrun the MCP handler caught still halts the fan-out."""

    class _ToolCallAgent(_UsageAgent):
        async def run(self, ctx: AgentRunContext) -> AgentResult:
            self.calls += 1
            assert ctx.budget_tracker is not None
            with pytest.raises(BudgetExhausted):
                ctx.budget_tracker.record_tool_call()
            return AgentResult(success=True, output="ok")

    tracker = BudgetTracker(bounds=replace(resolve_run_bounds(env={}), tool_call_budget=0))
    agent = _ToolCallAgent(AgentResult(success=True, output="ok"), is_file_group=True)
    env = _fanout_env(tmp_path, monkeypatch, agent=agent, tracker=tracker)

    with pytest.raises(BudgetExhausted) as exc_info:
        await _run_fanout(env)

    assert exc_info.value.kind == "tool_call"
    assert agent.calls == 1
    assert _run_health_messages(env) == []


async def test_an_ordinary_group_failure_still_lets_its_peers_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: a failing reviewer is isolated to its group; nothing halts."""

    class _FirstFails(_UsageAgent):
        async def run(self, ctx: AgentRunContext) -> AgentResult:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("provider unavailable")
            return AgentResult(success=True, output="ok", usage=_SMALL_USAGE)

    agent = _FirstFails(AgentResult(success=True, output="ok"), is_file_group=True)
    env = _fanout_env(tmp_path, monkeypatch, agent=agent)

    summary = await _run_fanout(env)

    assert agent.calls == 3
    assert summary.halted is None
    assert summary.skipped == ()
    assert [group_id for group_id, _reason in summary.failures] == ["group-1"]
    assert len(_run_health_messages(env)) == 1
    assert env.tracker.last_exhausted is None


# --------------------------------------------------------------------------- abnormal termination (#1588)

#: What the reviewer streamed before it timed out or raised.
_OBSERVED_INPUT = 30_000
_OBSERVED_OUTPUT = 6_000
_OBSERVED_COST = 0.25


class _AbnormalAgent:
    """Streams one step (or nothing), then times out or raises before reporting usage."""

    name = "opencode"

    def __init__(self, *, ending: str, streams: bool) -> None:
        self.ending = ending
        self.streams = streams
        self.calls = 0

    async def install(self) -> None:
        return None

    async def run(self, ctx: AgentRunContext) -> AgentResult:
        from mergecraft.agents.stream_budget import charge_review_stream_step

        self.calls += 1
        reason = (
            charge_review_stream_step(
                {"input_tokens": _OBSERVED_INPUT, "output_tokens": _OBSERVED_OUTPUT},
                budget_tracker=ctx.budget_tracker,
                provider_budget=None,
                stream_charges=ctx.stream_charges,
                cost_usd=_OBSERVED_COST,
            )
            if self.streams
            else None
        )
        assert reason is None
        if self.ending == "timeout":
            # Never set: the dispatch's own deadline is what ends this reviewer.
            await asyncio.Event().wait()
        raise RuntimeError("provider connection reset")


@pytest.mark.parametrize("ending", ["timeout", "raise"])
async def test_abnormal_termination_lists_the_observed_partial_usage_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    from mergecraft.utils.run_bounds import token_summary_from_usage

    agent = _AbnormalAgent(ending=ending, streams=True)
    env = _build_env(tmp_path, monkeypatch, agent=agent)

    summary = await run_pending_roster_reviewers(
        tool_context=env.tool_context,
        base_run_ctx=env.base_ctx,
        settings=env.settings,
        payload=_PAYLOAD,
        repo_root=env.root,
        per_reviewer_timeout_s=0.05,
    )

    assert env.tool_state.usage_entries == [
        AgentUsage(
            agent=agent.name,
            input_tokens=_OBSERVED_INPUT,
            output_tokens=_OBSERVED_OUTPUT,
            cost_usd=_OBSERVED_COST,
        )
    ]
    assert env.tracker.tokens_used == _OBSERVED_INPUT + _OBSERVED_OUTPUT
    assert env.tracker.cost_used == pytest.approx(_OBSERVED_COST)
    rendered = token_summary_from_usage(env.tool_state.usage_entries, budget_tracker=env.tracker)
    assert rendered is not None
    assert "context expansion" not in rendered
    assert f"{_OBSERVED_INPUT:,} input / {_OBSERVED_OUTPUT:,} output used" in rendered
    # The reviewer's own failure reason survives.
    expected = "timed out" if ending == "timeout" else "RuntimeError: provider connection reset"
    assert expected in env.tool_state.reviewer_dispatch_errors["reviewer2"]
    assert summary.hard_error is not None
    assert expected in summary.hard_error


@pytest.mark.parametrize("ending", ["timeout", "raise"])
async def test_abnormal_termination_without_usage_fabricates_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    agent = _AbnormalAgent(ending=ending, streams=False)
    env = _build_env(tmp_path, monkeypatch, agent=agent)

    await run_pending_roster_reviewers(
        tool_context=env.tool_context,
        base_run_ctx=env.base_ctx,
        settings=env.settings,
        payload=_PAYLOAD,
        repo_root=env.root,
        per_reviewer_timeout_s=0.05,
    )

    assert env.tool_state.usage_entries == []
    assert env.tracker.tokens_used == 0
    assert env.tracker.cost_used == 0.0
    assert "reviewer2" in env.tool_state.reviewer_dispatch_errors


async def test_an_exhausted_run_budget_dispatches_no_secondary_reviewer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#1584 — an exhaustion already on the tracker opens no further paid dispatch."""
    agent = _UsageAgent(AgentResult(success=True, output="ok", usage=_SMALL_USAGE))
    tracker = BudgetTracker(bounds=replace(resolve_run_bounds(env={}), tool_call_budget=0))
    with pytest.raises(BudgetExhausted):
        tracker.record_tool_call()
    env = _build_env(tmp_path, monkeypatch, agent=agent, tracker=tracker)

    summary = await _run_roster(env)

    assert agent.calls == 0
    assert env.tool_state.usage_entries == []
    reason = env.tool_state.reviewer_dispatch_errors["reviewer2"]
    assert reason.startswith("secondary reviewer 'reviewer2' was not dispatched")
    assert "tool-call budget exhausted" in reason
    assert summary.hard_error == reason


async def test_an_exhaustion_during_one_level_skips_the_next_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#1584 — a later dispatch level never starts once an earlier one spent the budget."""

    class _ToolCallOverrun(_UsageAgent):
        async def run(self, ctx: AgentRunContext) -> AgentResult:
            assert ctx.budget_tracker is not None
            with pytest.raises(BudgetExhausted):
                ctx.budget_tracker.record_tool_call()
            return await super().run(ctx)

    agent = _ToolCallOverrun(AgentResult(success=True, output="ok", usage=_SMALL_USAGE))
    tracker = BudgetTracker(bounds=replace(resolve_run_bounds(env={}), tool_call_budget=0))
    config = _config(
        extra="""  reviewer3:
    role: reviewer
    after: reviewer2
    modelChain:
      - openai/gpt-5.3-codex
"""
    )
    env = _build_env(tmp_path, monkeypatch, agent=agent, config=config, tracker=tracker)

    summary = await _run_roster(env)

    assert agent.calls == 1
    assert summary.dispatched_agent_ids == ("reviewer2",)
    reason = env.tool_state.reviewer_dispatch_errors["reviewer3"]
    assert reason.startswith("secondary reviewer 'reviewer3' was not dispatched")
    assert summary.hard_error == reason
