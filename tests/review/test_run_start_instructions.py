"""Every attempt reuses the instructions resolved at run start.

A harness-fallback attempt and a server-side reviewer run after an earlier
attempt may have checked the reviewed head out into the workspace, so neither
may render instructions from the tree again: they take the run-start entry for
their harness, and an attempt with no entry does not run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import mergecraft.main as main_mod
from mergecraft.agents.shared import AgentResult, ResolvedInstructions
from mergecraft.config.settings import RepoInfo, RepoSettings, RunContextData
from tests.support.publication import RecordingReviewGitHub, publication_ctx, run_ctx_for

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class _Harness:
    def __init__(self, name: str) -> None:
        self.name = name
        self.seen: list[ResolvedInstructions] = []

    async def install(self) -> None:
        return None

    async def run(self, ctx: Any) -> AgentResult:
        self.seen.append(ctx.instructions)
        return AgentResult(success=True, output="ok")


def _no_render(**_kwargs: Any) -> Any:
    msg = "instructions were rendered after run start"
    raise AssertionError(msg)


def _fallback_ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, harness: _Harness) -> Any:
    tool_context = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    primary = ResolvedInstructions(system="primary run-start", user="review")
    run = main_mod.RunContext(
        settings=RepoSettings(),
        tool_context=tool_context,
        tool_state=tool_context.tool_state,
        run_ctx=run_ctx_for(tool_context),
        tmpdir=tool_context.tmpdir,
    )
    run.run_ctx = run_ctx_for(tool_context)
    run.run_ctx.instructions = primary
    run.run_context = RunContextData(
        repo=RepoInfo(owner="acme", name="demo"), repoSettings=RepoSettings()
    )
    run.agent = _Harness("claude")  # type: ignore[assignment]
    run.agent_id = "claude"  # type: ignore[assignment]
    run.use_model_chain = True
    run.run_start_instructions = {"claude": primary}

    async def _chain(*, run_once: Any, **_kwargs: Any) -> tuple[str, AgentResult]:
        return "openai/gpt-5.3-codex", await run_once("openai/gpt-5.3-codex")

    monkeypatch.setattr(main_mod, "run_with_model_chain", _chain)
    monkeypatch.setattr(main_mod, "resolve_runtime_agent", lambda **_: harness)
    monkeypatch.setattr(main_mod, "resolve_instructions", _no_render)
    return run


async def test_a_harness_fallback_attempt_uses_the_run_start_instructions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _Harness("codex")
    run = _fallback_ctx(tmp_path, monkeypatch, harness)
    run_start = ResolvedInstructions(system="codex run-start", user="review")
    run.run_start_instructions["codex"] = run_start

    _slug, result = await main_mod._run_agent_task_with_deadline(run)

    assert result.success is True
    assert harness.seen == [run_start]
    assert harness.seen[0] is run_start


async def test_a_fallback_attempt_without_run_start_instructions_does_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _Harness("codex")
    run = _fallback_ctx(tmp_path, monkeypatch, harness)

    _slug, result = await main_mod._run_agent_task_with_deadline(run)

    assert result.success is False
    assert "run start" in (result.error or "")
    assert harness.seen == []


async def test_a_secondary_reviewer_uses_the_run_start_instructions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.agents.registry import ResolvedAgentModel
    from mergecraft.config.settings import load_repo_settings
    from mergecraft.review.roster_execution import run_pending_roster_reviewers
    from tests.cli.support_agent_roster import two_reviewer_config, write_config

    write_config(tmp_path, two_reviewer_config())
    monkeypatch.chdir(tmp_path)
    tool_context = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    harness = _Harness("opencode")
    monkeypatch.setattr(
        "mergecraft.review.roster_execution.resolve_runtime_agent", lambda **_: harness
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
    monkeypatch.setattr("mergecraft.utils.instructions.resolve_instructions", _no_render)
    run_start = ResolvedInstructions(system="opencode run-start", user="review")

    summary = await run_pending_roster_reviewers(
        tool_context=tool_context,
        base_run_ctx=run_ctx_for(tool_context),
        settings=load_repo_settings(root=tmp_path),
        payload={"event": {"trigger": "unknown"}},
        repo_root=tmp_path,
        instructions_for={"opencode": run_start}.get,
    )

    assert summary.hard_error is None
    assert len(harness.seen) == 1
    assert harness.seen[0].system.startswith("opencode run-start")
