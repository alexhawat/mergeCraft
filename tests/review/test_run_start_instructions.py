"""Every attempt reuses the instructions resolved at run start.

A harness-fallback attempt and a server-side reviewer run after an earlier
attempt may have checked the reviewed head out into the workspace, so neither
may render instructions from the tree again: they take the run-start entry for
their harness, and an attempt with no entry does not run.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

import pytest

import mergecraft.main as main_mod
from mergecraft.agents.shared import AgentResult, ResolvedInstructions
from mergecraft.config.settings import RepoInfo, RepoSettings, RunContextData
from tests.support.publication import RecordingReviewGitHub, publication_ctx, run_ctx_for

if TYPE_CHECKING:
    from pathlib import Path


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


@pytest.mark.parametrize(
    "scope",
    [
        pytest.param("bound", id="bound-rename"),
        pytest.param("operator-owned", id="operator-owned-base"),
        pytest.param("base-drift", id="base-drift"),
        pytest.param("head-drift", id="head-drift"),
        pytest.param("incomplete", id="incomplete-listing"),
        pytest.param("failed", id="failed-listing"),
        pytest.param("malformed", id="malformed-listing"),
        pytest.param("missing-base", id="unreadable-base-config"),
    ],
)
async def test_run_start_instructions_use_bound_scope_and_base_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scope: str
) -> None:
    from mergecraft.review_policy.ignore_paths import ReviewIgnore
    from tests.context.support import REPO_INSTRUCTIONS_HEADER, fenced_blocks

    base_sha = "a" * 40
    head_sha = "b" * 40
    base_config = """
review:
  instructionBundleByteCap: 2000
  pathInstructions:
    - glob: packages/z/**/*.py
      text: BASE_SCOPED_RULE
    - glob: packages/zzz/**/*.py
      text: UNMATCHED_RULE
"""
    head_config = RepoSettings.model_validate(
        {"review": {"pathInstructions": [{"glob": "**", "text": "HEAD_SCOPED_RULE"}]}}
    )
    head_file = tmp_path / ".mergecraft" / "config.yaml"
    head_file.parent.mkdir()
    head_file.write_text(
        "review:\n  instructionBundleByteCap: 64\n  pathInstructions:\n"
        "    - glob: '**'\n      text: HEAD_SCOPED_RULE\n",
        encoding="utf-8",
    )
    config_refs: list[str] = []
    file_calls: list[int] = []
    identity_reads: list[str] = []

    class GitHub(RecordingReviewGitHub):
        async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
            identity_reads.append("pull")
            return {
                "base": {"sha": "d" * 40 if scope == "base-drift" else base_sha},
                "head": {"sha": "e" * 40 if scope == "head-drift" and file_calls else head_sha},
            }

        async def get(self, path: str, **kwargs: Any) -> Any:
            if path.endswith("/files"):
                file_calls.append(kwargs["params"]["page"])
                if scope == "failed":
                    raise RuntimeError("listing unavailable")
                if scope == "incomplete":
                    return [{"filename": "packages/z/src.py"}] * 100
                if scope == "malformed":
                    return [{"filename": "packages/z/src.py"}, {"filename": None}]
                return [
                    {"filename": "packages/zz/renamed.py", "previous_filename": "packages/z/src.py"}
                ]
            assert path.endswith("/contents/.mergecraft/config.yaml")
            config_refs.append(kwargs["params"]["ref"])
            if scope == "missing-base":
                return None
            return {
                "type": "file",
                "encoding": "base64",
                "content": base64.b64encode(base_config.encode()).decode(),
            }

    for package, body in [("a", "UNRELATED_" * 1000), ("z", "NEAREST_PACKAGE_RULE")]:
        inst = tmp_path / "packages" / package / "AGENTS.md"
        inst.parent.mkdir(parents=True)
        inst.write_text(body, encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    operator_owned = scope == "operator-owned"
    monkeypatch.setenv(
        "GITHUB_EVENT_NAME", "pull_request_target" if operator_owned else "pull_request"
    )
    github = GitHub()
    tool_context = publication_ctx(tmp_path, github=github, trust_tier="untrusted")
    tool_context.tool_state.review_ignore = ReviewIgnore(patterns=("packages/z/**",))
    run = main_mod.RunContext(
        settings=head_config,
        settings_snapshot_operator_owned=operator_owned,
        tool_context=tool_context,
        tool_state=tool_context.tool_state,
        run_context=RunContextData(
            repo=RepoInfo(owner="acme", name="demo"), repoSettings=head_config
        ),
        tmpdir=tool_context.tmpdir,
        agent_id="claude",
        gh_event={
            "pull_request": {"number": 7, "base": {"sha": base_sha}, "head": {"sha": head_sha}}
        },
        payload={"event": {"trigger": "pull_request", "headSha": head_sha}},
    )
    monkeypatch.setattr(
        main_mod, "start_mcp_http_server", lambda *a, **kw: ("http://local/mcp", lambda: None)
    )
    monkeypatch.setattr(main_mod, "start_installation", lambda *_: None)
    monkeypatch.setattr(main_mod, "install_bundled_skills", lambda **_: None)
    monkeypatch.setattr(main_mod, "_run_start_harnesses", lambda _: ["claude", "codex"])

    async def seed(**kwargs: Any) -> str:
        return ""

    monkeypatch.setattr(main_mod, "seed_learnings_file", seed)

    await main_mod._prepare_agent_dispatch(run)

    assert config_refs == [base_sha]
    assert set(run.run_start_instructions) == {"claude", "codex"}
    for instructions in run.run_start_instructions.values():
        prompt = instructions.full
        blocks = fenced_blocks(prompt)
        assert REPO_INSTRUCTIONS_HEADER not in prompt
        assert "HEAD_SCOPED_RULE" not in prompt
        assert "UNMATCHED_RULE" not in prompt
        if scope in {"bound", "operator-owned"}:
            assert any("BASE_SCOPED_RULE" in block for block in blocks)
            assert any("NEAREST_PACKAGE_RULE" in block for block in blocks)
        else:
            assert "BASE_SCOPED_RULE" not in prompt
    if scope == "base-drift":
        assert file_calls == []
    elif scope == "incomplete":
        assert file_calls == list(range(1, 31))
    else:
        assert file_calls == [1]
    if scope == "head-drift":
        assert identity_reads == ["pull", "pull"]
