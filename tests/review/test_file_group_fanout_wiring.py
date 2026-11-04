"""File-group fan-out wired into the server-side roster dispatch.

A large diff is split into bounded read-only file groups, each reviewed by its
own dispatch under the ``file-group/<group-id>`` agent id, with findings
aggregated through ``record_reviewer_dispatch_run``. The feature is off by
default, runs groups sequentially by default, and a failed group degrades the
run (one run-scoped ``Minor`` row on the run-health partition) instead of
failing it. A diff below both size thresholds keeps today's single-agent path.

Seams this suite pins (the test-plan doc repeats them):

* ``mergecraft.review.roster_execution.run_file_group_reviewers(*, tool_context,
  base_run_ctx, settings, payload, repo_root, remaining_timeout_s=None)`` returns
  a ``FanoutSummary``; ``remaining_timeout_s`` has the same shape as
  ``run_pending_roster_reviewers``' (a ``Callable[[], float | None]``).
* A failed group's run-health row is a ``Finding``-shaped row with
  ``scope="run"`` appended to ``ToolState.agent_findings`` — the lane the packet
  loader reads and ``evidence.build._partition_findings`` splits into
  ``run_health``.
* ``mergecraft.main._run_server_roster_reviewers_if_needed`` calls the fan-out
  before ``run_pending_roster_reviewers``, and only when enabled.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from mergecraft.agents.registry import ResolvedAgentModel, load_registry
from mergecraft.agents.shared import AgentResult, AgentRunContext
from mergecraft.analyzers.finding import make_finding
from mergecraft.config.settings import RepoSettings, load_repo_settings
from mergecraft.evidence.build import _partition_findings
from mergecraft.evidence.merge import typed_findings_from_rows_with_drops
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import (
    ToolState,
    init_tool_state,
    primary_repo_state,
    record_reviewer_dispatch_error,
    record_reviewer_dispatch_run,
)
from mergecraft.review import roster_execution
from mergecraft.review.file_group_fanout import FanoutSummary, plan_file_groups
from mergecraft.review.roster_execution import (
    RosterExecutionSummary,
    apply_roster_failure,
    roster_dispatch_gaps,
    run_pending_roster_reviewers,
)
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.instructions import ResolvedInstructions
from tests.agents.conftest import make_agent_run_context
from tests.cli.support_agent_roster import DEFAULT_MODELS_YAML, two_reviewer_config, write_config

_PAYLOAD: dict[str, Any] = {"event": {"trigger": "unknown"}}
_PRIMARY_MODEL = "anthropic/claude-sonnet"
_SECONDARY_MODEL = "openai/gpt-5.3-codex"
_FAILURE_REASON = "provider unavailable"
_GROUP_PREFIX = "file-group/"


# --------------------------------------------------------------------------- helpers


def _diff(file_count: int, lines_per_file: int) -> str:
    """A unified diff that only adds lines, one hunk per file."""
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
_SMALL_DIFF = _diff(2, 5)


def _yaml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _fanout_block(**fields: object) -> str:
    """A ``review.fileGroupFanout`` YAML block; no fields means no block at all."""
    if not fields:
        return ""
    lines = ["", "review:", "  fileGroupFanout:"]
    lines.extend(f"    {key}: {_yaml_scalar(value)}" for key, value in fields.items())
    return "\n".join(lines) + "\n"


def _single_reviewer_config(*, reviewer_timeout_s: int | None = None, **fanout: object) -> str:
    timeout_line = f"\n    timeoutS: {reviewer_timeout_s}" if reviewer_timeout_s else ""
    return (
        DEFAULT_MODELS_YAML
        + f"""
agents:
  reviewer:
    modelChain:
      - {_PRIMARY_MODEL}{timeout_line}
"""
        + _fanout_block(**fanout)
    )


def _two_reviewer_config(**fanout: object) -> str:
    return two_reviewer_config(_fanout_block(**fanout))


def _prompt_text(instructions: Any) -> str:
    system = getattr(instructions, "system", "") or ""
    user = getattr(instructions, "user", "") or ""
    full = getattr(instructions, "full", "") or ""
    return f"{system}\n{user}\n{full}"


def _group_paths(diff_text: str, **plan_kwargs: int) -> dict[str, tuple[str, ...]]:
    plan = plan_file_groups(diff_text, **plan_kwargs)
    return {group.group_id: group.paths for group in plan.groups}


def _group_agent_id(group_id: str) -> str:
    return f"{_GROUP_PREFIX}{group_id}"


def _bare_group_id(identifier: str) -> str:
    return identifier.removeprefix(_GROUP_PREFIX)


def _fingerprint_for(group_id: str) -> str:
    return f"fp-{group_id}"


def _agent_finding_row(group_id: str, path: str) -> dict[str, Any]:
    finding = make_finding(
        tool="review",
        rule_id="agent:file-group",
        category="Data Integrity & Atomicity",
        severity="Minor",
        confidence="likely",
        message=f"finding raised inside {group_id}",
        path=path,
        start_line=1,
        end_line=1,
        source="agent",
        introduced_by_pr="true",
        fingerprint=_fingerprint_for(group_id),
    )
    return finding.model_dump(mode="json")


class _RecordingAgent:
    """Fake reviewer runtime: records every dispatch and the overlap between them.

    A dispatch whose prompt names a planned group's paths acts as that group's
    reviewer and appends one finding row (the way a reviewer's finding tool
    does). Any other dispatch acts as the secondary roster reviewer and records
    its own run under ``reviewer2``.
    """

    name = "opencode"

    def __init__(
        self,
        groups: dict[str, tuple[str, ...]] | None = None,
        *,
        fail_group: str | None = None,
        fail_mode: str = "raise",
        delay_s: float = 0.0,
        hang_s: float = 0.0,
    ) -> None:
        self.groups = dict(groups or {})
        self.fail_group = fail_group
        self.fail_mode = fail_mode
        self.delay_s = delay_s
        self.hang_s = hang_s
        self.calls: list[tuple[str, str]] = []
        self.events: list[tuple[str, str]] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def install(self) -> None:
        return None

    def group_for(self, prompt: str) -> str | None:
        matches = [
            group_id
            for group_id, paths in self.groups.items()
            if any(path in prompt for path in paths)
        ]
        return matches[0] if matches else None

    def group_calls(self) -> list[tuple[str, str]]:
        return [(model, prompt) for model, prompt in self.calls if self.group_for(prompt)]

    async def run(self, ctx: AgentRunContext) -> AgentResult:
        prompt = _prompt_text(ctx.instructions)
        self.calls.append((ctx.resolved_model or "", prompt))
        group_id = self.group_for(prompt)
        if group_id is None:
            record_reviewer_dispatch_run(
                ctx.tool_state,
                agent_id="reviewer2",
                findings=[
                    {"path": "src/a.py", "body": "from secondary", "severity": "Minor", "line": 1}
                ],
                model_slug=ctx.resolved_model,
            )
            return AgentResult(success=True, output="ok")
        self.events.append(("start", group_id))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            if self.hang_s:
                await asyncio.sleep(self.hang_s)
            if group_id == self.fail_group:
                if self.fail_mode == "raise":
                    raise RuntimeError(_FAILURE_REASON)
                return AgentResult(success=False, error=_FAILURE_REASON)
            ctx.tool_state.agent_findings.append(
                _agent_finding_row(group_id, self.groups[group_id][0])
            )
            return AgentResult(success=True, output="ok")
        finally:
            self.in_flight -= 1
            self.events.append(("finish", group_id))


@dataclass
class _Env:
    root: Path
    tool_state: ToolState
    tool_context: ToolContext
    settings: RepoSettings
    base_ctx: AgentRunContext
    diff_path: Path | None
    agent: _RecordingAgent


def _patch_dispatch_seams(
    monkeypatch: pytest.MonkeyPatch,
    agent: _RecordingAgent,
    *,
    credential_available: bool,
) -> None:
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.resolve_runtime_agent",
        lambda **kwargs: agent,
    )
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.credential_status_for_slug",
        lambda *args, **kwargs: type("S", (), {"available": credential_available})(),
    )
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.format_credential_gap_message",
        lambda **kwargs: f"no credential configured for {kwargs.get('slug')}",
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
        "mergecraft.review.roster_execution.resolve_agent_model", _resolved, raising=False
    )
    monkeypatch.setattr(
        "mergecraft.utils.instructions.resolve_instructions",
        lambda **kwargs: ResolvedInstructions(system="test", user="review"),
    )
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.resolve_instructions",
        lambda **kwargs: ResolvedInstructions(system="test", user="review"),
        raising=False,
    )
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.subagent_denied_tool_names",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.verifier_denied_tool_names",
        lambda *args, **kwargs: [],
    )


def _build_env(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    config: str,
    diff: str | None,
    agent: _RecordingAgent,
    credential_available: bool = True,
    write_diff: bool = True,
) -> _Env:
    root.mkdir(parents=True, exist_ok=True)
    write_config(root, config)
    monkeypatch.chdir(root)
    scratch = root / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    tool_state = init_tool_state(owner="local", name="demo", dir=str(root))
    diff_path: Path | None = None
    if diff is not None:
        diff_path = scratch / "pr.diff"
        if write_diff:
            diff_path.write_text(diff, encoding="utf-8")
        primary_repo_state(tool_state).diff_path = str(diff_path)
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
    _patch_dispatch_seams(monkeypatch, agent, credential_available=credential_available)
    return _Env(
        root=root,
        tool_state=tool_state,
        tool_context=tool_context,
        settings=settings,
        base_ctx=base_ctx,
        diff_path=diff_path,
        agent=agent,
    )


def _require_run_file_group_reviewers() -> Any:
    fn = getattr(roster_execution, "run_file_group_reviewers", None)
    if not callable(fn):
        pytest.fail(
            "mergecraft.review.roster_execution.run_file_group_reviewers is not implemented"
        )
    return fn


async def _fan_out(env: _Env, *, remaining_timeout_s: Any = None) -> FanoutSummary:
    fn = _require_run_file_group_reviewers()
    summary = await fn(
        tool_context=env.tool_context,
        base_run_ctx=env.base_ctx,
        settings=env.settings,
        payload=_PAYLOAD,
        repo_root=env.root,
        remaining_timeout_s=remaining_timeout_s,
    )
    assert isinstance(summary, FanoutSummary)
    return summary


async def _run_roster(env: _Env) -> RosterExecutionSummary:
    return await run_pending_roster_reviewers(
        tool_context=env.tool_context,
        base_run_ctx=env.base_ctx,
        settings=env.settings,
        payload=_PAYLOAD,
        repo_root=env.root,
        per_reviewer_timeout_s=30.0,
    )


def _group_runs(tool_state: ToolState) -> dict[str, Any]:
    return {
        run.agent_id: run
        for run in tool_state.reviewer_dispatch_runs
        if run.agent_id.startswith(_GROUP_PREFIX)
    }


def _run_scoped_rows(tool_state: ToolState) -> list[Any]:
    rows: list[Any] = []
    for row in tool_state.agent_findings:
        scope = row.get("scope") if isinstance(row, dict) else getattr(row, "scope", None)
        if scope == "run":
            rows.append(row)
    return rows


def _failed_group_ids(summary: FanoutSummary) -> set[str]:
    return {_bare_group_id(group_id) for group_id, _reason in summary.failures}


# --------------------------------------------------------------------------- default off


@pytest.mark.parametrize(
    "config",
    [
        pytest.param(_single_reviewer_config(), id="no-fanout-block"),
        pytest.param(_single_reviewer_config(enabled=False), id="explicitly-disabled"),
    ],
)
async def test_disabled_fanout_returns_an_empty_summary_and_dispatches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: str
) -> None:
    """Off by default: even a large diff is not planned or dispatched."""
    agent = _RecordingAgent(_group_paths(_LARGE_DIFF))
    env = _build_env(tmp_path, monkeypatch, config=config, diff=_LARGE_DIFF, agent=agent)

    summary = await _fan_out(env)

    assert summary == FanoutSummary()
    assert agent.calls == []
    assert env.tool_state.reviewer_dispatch_runs == []
    assert env.tool_state.reviewer_dispatch_errors == {}


# --------------------------------------------------------------------------- small diff


async def test_small_diff_keeps_the_secondary_call_sequence_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enabled + a diff below both thresholds: the dispatches are exactly today's."""
    baseline_agent = _RecordingAgent()
    baseline = _build_env(
        tmp_path / "baseline",
        monkeypatch,
        config=_two_reviewer_config(),
        diff=_SMALL_DIFF,
        agent=baseline_agent,
    )
    baseline_summary = await _run_roster(baseline)

    fanout_agent = _RecordingAgent()
    enabled = _build_env(
        tmp_path / "enabled",
        monkeypatch,
        config=_two_reviewer_config(enabled=True),
        diff=_SMALL_DIFF,
        agent=fanout_agent,
    )
    fanout_summary = await _fan_out(enabled)
    enabled_summary = await _run_roster(enabled)

    assert fanout_summary == FanoutSummary()
    assert fanout_agent.calls == baseline_agent.calls
    assert [model for model, _prompt in fanout_agent.calls] == [_SECONDARY_MODEL]
    assert [run.agent_id for run in enabled.tool_state.reviewer_dispatch_runs] == [
        run.agent_id for run in baseline.tool_state.reviewer_dispatch_runs
    ]
    assert enabled_summary == baseline_summary


@pytest.mark.parametrize(
    ("diff", "write_diff"),
    [
        pytest.param(None, True, id="no-diff-path-recorded"),
        pytest.param(_LARGE_DIFF, False, id="diff-path-missing-on-disk"),
    ],
)
async def test_enabled_without_a_readable_diff_dispatches_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    diff: str | None,
    write_diff: bool,
) -> None:
    """No checkout diff to plan from is the single-agent path, never an exception."""
    agent = _RecordingAgent(_group_paths(_LARGE_DIFF))
    env = _build_env(
        tmp_path,
        monkeypatch,
        config=_single_reviewer_config(enabled=True),
        diff=diff,
        agent=agent,
        write_diff=write_diff,
    )

    summary = await _fan_out(env)

    assert summary == FanoutSummary()
    assert agent.calls == []
    assert _group_runs(env.tool_state) == {}


# --------------------------------------------------------------------------- large diff


async def test_large_diff_dispatches_one_reviewer_per_planned_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    groups = _group_paths(_LARGE_DIFF, max_groups=4)
    agent = _RecordingAgent(groups)
    env = _build_env(
        tmp_path,
        monkeypatch,
        config=_single_reviewer_config(enabled=True, maxGroups=4),
        diff=_LARGE_DIFF,
        agent=agent,
    )

    summary = await _fan_out(env)

    assert len(groups) == 4
    assert len(agent.group_calls()) == 4
    assert set(_group_runs(env.tool_state)) == {
        "file-group/group-1",
        "file-group/group-2",
        "file-group/group-3",
        "file-group/group-4",
    }
    assert summary.degraded is False
    assert len(summary.results) == 4


@pytest.mark.parametrize("max_groups", [1, 3, 6])
async def test_group_count_never_exceeds_max_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, max_groups: int
) -> None:
    diff = _diff(40, 25)
    groups = _group_paths(diff, max_groups=max_groups)
    agent = _RecordingAgent(groups)
    env = _build_env(
        tmp_path,
        monkeypatch,
        config=_single_reviewer_config(enabled=True, maxGroups=max_groups),
        diff=diff,
        agent=agent,
    )

    await _fan_out(env)

    assert len(agent.group_calls()) == max_groups
    assert set(_group_runs(env.tool_state)) == {
        _group_agent_id(f"group-{index + 1}") for index in range(max_groups)
    }


async def test_each_group_prompt_names_only_its_own_paths_and_the_shared_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    groups = _group_paths(_LARGE_DIFF, max_groups=4)
    agent = _RecordingAgent(groups)
    env = _build_env(
        tmp_path,
        monkeypatch,
        config=_single_reviewer_config(enabled=True, maxGroups=4),
        diff=_LARGE_DIFF,
        agent=agent,
    )

    await _fan_out(env)

    assert env.diff_path is not None
    seen: set[str] = set()
    for _model, prompt in agent.group_calls():
        owners = {
            group_id for group_id, paths in groups.items() if any(path in prompt for path in paths)
        }
        assert len(owners) == 1, f"prompt names paths of several groups: {sorted(owners)}"
        (group_id,) = owners
        seen.add(group_id)
        for path in groups[group_id]:
            assert path in prompt
        assert str(env.diff_path) in prompt
        assert roster_execution._ROSTER_SUBMIT_INSTRUCTIONS in prompt
    assert seen == set(groups)


async def test_group_findings_are_recorded_under_the_group_agent_id_with_model_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    groups = _group_paths(_LARGE_DIFF, max_groups=3)
    agent = _RecordingAgent(groups)
    env = _build_env(
        tmp_path,
        monkeypatch,
        config=_single_reviewer_config(enabled=True, maxGroups=3),
        diff=_LARGE_DIFF,
        agent=agent,
    )

    await _fan_out(env)

    runs = _group_runs(env.tool_state)
    assert set(runs) == {_group_agent_id(group_id) for group_id in groups}
    for group_id in groups:
        run = runs[_group_agent_id(group_id)]
        assert run.model_slug == _PRIMARY_MODEL
        assert [row.get("fingerprint") for row in run.findings] == [_fingerprint_for(group_id)]
    # The reviewer runtime's agent id is restored after the dispatches.
    assert env.tool_context.agent_id == "opencode"


async def test_configured_binding_selects_the_group_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``binding`` names a registry agent; ``None`` would reuse the primary reviewer."""
    groups = _group_paths(_LARGE_DIFF, max_groups=2)
    agent = _RecordingAgent(groups)
    env = _build_env(
        tmp_path,
        monkeypatch,
        config=_two_reviewer_config(enabled=True, maxGroups=2, binding="reviewer2"),
        diff=_LARGE_DIFF,
        agent=agent,
    )

    await _fan_out(env)

    assert [model for model, _prompt in agent.group_calls()] == [_SECONDARY_MODEL] * 2
    assert {run.model_slug for run in _group_runs(env.tool_state).values()} == {_SECONDARY_MODEL}


# --------------------------------------------------------------------------- degradation


@pytest.mark.parametrize("fail_mode", ["raise", "result"])
async def test_a_failed_group_degrades_to_one_run_health_minor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_mode: str
) -> None:
    """A group that raises or returns a failed result is recorded, never re-raised."""
    groups = _group_paths(_LARGE_DIFF, max_groups=3)
    agent = _RecordingAgent(groups, fail_group="group-2", fail_mode=fail_mode)
    env = _build_env(
        tmp_path,
        monkeypatch,
        config=_single_reviewer_config(enabled=True, maxGroups=3),
        diff=_LARGE_DIFF,
        agent=agent,
    )

    summary = await _fan_out(env)

    assert summary.degraded is True
    assert _failed_group_ids(summary) == {"group-2"}
    assert _FAILURE_REASON in env.tool_state.reviewer_dispatch_errors["file-group/group-2"]

    rows = _run_scoped_rows(env.tool_state)
    typed, dropped = typed_findings_from_rows_with_drops(rows)
    assert dropped == 0
    assert len(typed) == 1
    health = typed[0]
    assert health.scope == "run"
    assert health.severity == "Minor"
    assert health.tool == "review"
    assert "group-2" in health.message
    assert _FAILURE_REASON in health.message
    change_findings, run_health = _partition_findings(typed)
    assert change_findings == []
    assert run_health is not None
    assert run_health.findings == typed


async def test_a_failed_group_keeps_every_other_groups_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    groups = _group_paths(_LARGE_DIFF, max_groups=3)
    agent = _RecordingAgent(groups, fail_group="group-2")
    env = _build_env(
        tmp_path,
        monkeypatch,
        config=_single_reviewer_config(enabled=True, maxGroups=3),
        diff=_LARGE_DIFF,
        agent=agent,
    )

    summary = await _fan_out(env)

    runs = _group_runs(env.tool_state)
    assert set(runs) == {"file-group/group-1", "file-group/group-3"}
    for group_id in ("group-1", "group-3"):
        fingerprints = [row.get("fingerprint") for row in runs[_group_agent_id(group_id)].findings]
        assert fingerprints == [_fingerprint_for(group_id)]
    # The run-health row never lands inside a reviewer run's findings.
    assert all(row.get("scope") != "run" for run in runs.values() for row in run.findings)
    assert len(summary.results) == 2


async def test_a_failed_group_is_never_a_roster_hard_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The secondary roster still dispatches and the run result is not rewritten."""
    groups = _group_paths(_LARGE_DIFF, max_groups=3)
    agent = _RecordingAgent(groups, fail_group="group-1")
    env = _build_env(
        tmp_path,
        monkeypatch,
        config=_two_reviewer_config(enabled=True, maxGroups=3),
        diff=_LARGE_DIFF,
        agent=agent,
    )

    fanout = await _fan_out(env)
    roster = await _run_roster(env)

    assert fanout.degraded is True
    assert roster.hard_error is None
    assert roster.dispatched_agent_ids == ("reviewer2",)
    primary = AgentResult(success=True, output="review text")
    assert apply_roster_failure(primary, roster) is primary


# --------------------------------------------------------------------------- concurrency


@pytest.mark.parametrize(
    "fanout",
    [
        pytest.param({"concurrency": 1}, id="concurrency-1"),
        pytest.param({}, id="default"),
    ],
)
async def test_sequential_fanout_finishes_each_group_before_starting_the_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fanout: dict[str, object]
) -> None:
    groups = _group_paths(_LARGE_DIFF, max_groups=4)
    agent = _RecordingAgent(groups, delay_s=0.02)
    env = _build_env(
        tmp_path,
        monkeypatch,
        config=_single_reviewer_config(enabled=True, maxGroups=4, **fanout),
        diff=_LARGE_DIFF,
        agent=agent,
    )

    await _fan_out(env)

    expected: list[tuple[str, str]] = []
    for index in range(1, 5):
        expected.extend([("start", f"group-{index}"), ("finish", f"group-{index}")])
    assert agent.events == expected
    assert agent.max_in_flight == 1


async def test_concurrency_three_never_runs_more_than_three_groups_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    diff = _diff(40, 25)
    groups = _group_paths(diff, max_groups=6)
    agent = _RecordingAgent(groups, delay_s=0.05)
    env = _build_env(
        tmp_path,
        monkeypatch,
        config=_single_reviewer_config(enabled=True, maxGroups=6, concurrency=3),
        diff=diff,
        agent=agent,
    )

    await _fan_out(env)

    assert agent.max_in_flight == 3
    assert len(_group_runs(env.tool_state)) == 6


# --------------------------------------------------------------------------- roster gaps


async def test_roster_gaps_ignore_file_group_rows_after_a_fanout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Group runs and errors neither satisfy nor create a secondary-reviewer gap."""
    groups = _group_paths(_LARGE_DIFF, max_groups=3)
    agent = _RecordingAgent(groups, fail_group="group-3")
    env = _build_env(
        tmp_path,
        monkeypatch,
        config=_two_reviewer_config(enabled=True, maxGroups=3),
        diff=_LARGE_DIFF,
        agent=agent,
    )
    registry = load_registry(settings=env.settings, repo_root=env.root)

    await _fan_out(env)

    assert len(_group_runs(env.tool_state)) == 2
    assert "file-group/group-3" in env.tool_state.reviewer_dispatch_errors
    assert roster_dispatch_gaps(registry, env.tool_state) == ("reviewer2",)

    await _run_roster(env)

    assert roster_dispatch_gaps(registry, env.tool_state) == ()


def test_roster_gaps_name_only_registry_reviewers_beside_group_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard: a recorded ``file-group/*`` row is never a configured reviewer."""
    write_config(tmp_path, two_reviewer_config())
    monkeypatch.chdir(tmp_path)
    registry = load_registry(settings=load_repo_settings(root=tmp_path), repo_root=tmp_path)
    tool_state = init_tool_state(owner="local", name="demo", dir=str(tmp_path))
    record_reviewer_dispatch_run(
        tool_state, agent_id="file-group/group-1", findings=[], model_slug=_PRIMARY_MODEL
    )
    record_reviewer_dispatch_error(tool_state, agent_id="file-group/group-2", reason="timeout")

    assert roster_dispatch_gaps(registry, tool_state) == ("reviewer2",)

    record_reviewer_dispatch_run(tool_state, agent_id="reviewer2", findings=[])

    assert roster_dispatch_gaps(registry, tool_state) == ()


# --------------------------------------------------------------------------- binding / credential gaps


async def test_missing_binding_is_a_recorded_error_not_an_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    groups = _group_paths(_LARGE_DIFF, max_groups=2)
    agent = _RecordingAgent(groups)
    env = _build_env(
        tmp_path,
        monkeypatch,
        config=_single_reviewer_config(enabled=True, maxGroups=2, binding="ghost-reviewer"),
        diff=_LARGE_DIFF,
        agent=agent,
    )

    summary = await _fan_out(env)

    assert summary.degraded is True
    assert agent.calls == []
    assert _group_runs(env.tool_state) == {}
    group_errors = {
        agent_id: reason
        for agent_id, reason in env.tool_state.reviewer_dispatch_errors.items()
        if agent_id.startswith(_GROUP_PREFIX)
    }
    assert group_errors
    assert all("ghost-reviewer" in reason for reason in group_errors.values())
    assert _run_scoped_rows(env.tool_state)


async def test_missing_credential_is_a_recorded_error_per_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    groups = _group_paths(_LARGE_DIFF, max_groups=2)
    agent = _RecordingAgent(groups)
    env = _build_env(
        tmp_path,
        monkeypatch,
        config=_single_reviewer_config(enabled=True, maxGroups=2),
        diff=_LARGE_DIFF,
        agent=agent,
        credential_available=False,
    )

    summary = await _fan_out(env)

    expected_reason = f"no credential configured for {_PRIMARY_MODEL}"
    assert agent.calls == []
    assert _failed_group_ids(summary) == {"group-1", "group-2"}
    for group_id in ("group-1", "group-2"):
        assert env.tool_state.reviewer_dispatch_errors[_group_agent_id(group_id)] == (
            expected_reason
        )
    assert len(_run_scoped_rows(env.tool_state)) == 2


# --------------------------------------------------------------------------- per-group timeout


@pytest.mark.parametrize(
    ("config", "remaining"),
    [
        pytest.param(
            _single_reviewer_config(enabled=True, maxGroups=1, perGroupTimeoutS=1),
            None,
            id="per-group-timeout",
        ),
        pytest.param(
            _single_reviewer_config(reviewer_timeout_s=1, enabled=True, maxGroups=1),
            None,
            id="binding-timeout",
        ),
        pytest.param(
            _single_reviewer_config(enabled=True, maxGroups=1),
            lambda: 1.0,
            id="remaining-run-budget",
        ),
    ],
)
async def test_group_timeout_is_the_smallest_of_its_three_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: str,
    remaining: Any,
) -> None:
    """``min(perGroupTimeoutS, binding timeout, remaining run budget)`` caps a group."""
    groups = _group_paths(_LARGE_DIFF, max_groups=1)
    agent = _RecordingAgent(groups, hang_s=15.0)
    env = _build_env(tmp_path, monkeypatch, config=config, diff=_LARGE_DIFF, agent=agent)

    started = time.monotonic()
    summary = await _fan_out(env, remaining_timeout_s=remaining)
    elapsed = time.monotonic() - started

    assert elapsed < 8.0
    assert _failed_group_ids(summary) == {"group-1"}
    assert "timed out" in env.tool_state.reviewer_dispatch_errors["file-group/group-1"].lower()
    assert len(_run_scoped_rows(env.tool_state)) == 1


# --------------------------------------------------------------------------- main.py seam


def _main_ctx(env: _Env) -> Any:
    from mergecraft.main import RunContext

    env.tool_state.selected_mode = "Review"
    return RunContext(
        settings=env.settings,
        tool_state=env.tool_state,
        tool_context=env.tool_context,
        run_ctx=env.base_ctx,
        payload=dict(_PAYLOAD),
        agent_deadline_monotonic=time.monotonic() + 120.0,
    )


def _patch_main_dispatchers(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fanout_summary: FanoutSummary,
    roster_summary: RosterExecutionSummary,
) -> tuple[list[str], list[dict[str, Any]]]:
    import mergecraft.main as main_module

    order: list[str] = []
    fanout_kwargs: list[dict[str, Any]] = []

    async def _fake_fanout(**kwargs: Any) -> FanoutSummary:
        order.append("file-groups")
        fanout_kwargs.append(kwargs)
        return fanout_summary

    async def _fake_roster(**kwargs: Any) -> RosterExecutionSummary:
        order.append("secondary-roster")
        return roster_summary

    for target in (roster_execution, main_module):
        monkeypatch.setattr(target, "run_file_group_reviewers", _fake_fanout, raising=False)
        monkeypatch.setattr(target, "run_pending_roster_reviewers", _fake_roster, raising=False)
    return order, fanout_kwargs


async def test_main_runs_the_fanout_before_the_secondary_roster_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.main import _run_server_roster_reviewers_if_needed

    env = _build_env(
        tmp_path,
        monkeypatch,
        config=_two_reviewer_config(enabled=True),
        diff=_LARGE_DIFF,
        agent=_RecordingAgent(),
    )
    roster_summary = RosterExecutionSummary(hard_error=None, dispatched_agent_ids=("reviewer2",))
    order, fanout_kwargs = _patch_main_dispatchers(
        monkeypatch, fanout_summary=FanoutSummary(), roster_summary=roster_summary
    )
    ctx = _main_ctx(env)

    result = await _run_server_roster_reviewers_if_needed(ctx)

    assert order == ["file-groups", "secondary-roster"]
    assert result is roster_summary
    (kwargs,) = fanout_kwargs
    assert kwargs["tool_context"] is ctx.tool_context
    assert kwargs["base_run_ctx"] is ctx.run_ctx
    assert kwargs["payload"] == ctx.payload
    remaining = kwargs["remaining_timeout_s"]
    assert callable(remaining)
    budget = remaining()
    assert budget is not None
    assert 1.0 <= budget <= 120.0


async def test_main_skips_the_fanout_when_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.main import _run_server_roster_reviewers_if_needed

    env = _build_env(
        tmp_path,
        monkeypatch,
        config=_two_reviewer_config(enabled=False),
        diff=_LARGE_DIFF,
        agent=_RecordingAgent(),
    )
    roster_summary = RosterExecutionSummary(hard_error=None, dispatched_agent_ids=("reviewer2",))
    order, fanout_kwargs = _patch_main_dispatchers(
        monkeypatch, fanout_summary=FanoutSummary(), roster_summary=roster_summary
    )

    result = await _run_server_roster_reviewers_if_needed(_main_ctx(env))

    assert order == ["secondary-roster"]
    assert fanout_kwargs == []
    assert result is roster_summary


async def test_main_never_folds_a_degraded_fanout_into_the_roster_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.main import _run_server_roster_reviewers_if_needed

    env = _build_env(
        tmp_path,
        monkeypatch,
        config=_two_reviewer_config(enabled=True),
        diff=_LARGE_DIFF,
        agent=_RecordingAgent(),
    )
    degraded = FanoutSummary(results=(), failures=(("group-2", _FAILURE_REASON),))
    roster_summary = RosterExecutionSummary(hard_error=None, dispatched_agent_ids=("reviewer2",))
    order, _kwargs = _patch_main_dispatchers(
        monkeypatch, fanout_summary=degraded, roster_summary=roster_summary
    )

    result = await _run_server_roster_reviewers_if_needed(_main_ctx(env))

    assert order == ["file-groups", "secondary-roster"]
    assert result is roster_summary
    assert result is not None
    assert result.hard_error is None
    primary = AgentResult(success=True, output="review text")
    assert apply_roster_failure(primary, result) is primary
