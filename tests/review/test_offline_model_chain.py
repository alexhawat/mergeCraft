"""Offline dispatch uses the shared model policy and checks terminal outcomes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mergecraft.agents.shared import AgentResult
from mergecraft.config.settings import RepoSettings
from mergecraft.review import offline_agent
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.agent_resolve import CredentialStatus
from mergecraft.utils.offline_diff import DiffMaterialization

PRIMARY = "anthropic/claude-sonnet"
BACKUP = "openai/gpt-5.3-codex"


@pytest.fixture
def dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {"models": [], "results": {}, "available": True}
    monkeypatch.delenv("MERGECRAFT_MODEL", raising=False)
    monkeypatch.setattr(offline_agent, "load_repo_settings", lambda **_: seen["settings"])
    monkeypatch.setattr(
        offline_agent,
        "start_mcp_http_server",
        lambda *a, **kw: ("http://localhost:1/mcp", lambda: None),
    )
    monkeypatch.setattr(offline_agent, "install_bundled_skills", lambda **_: None)
    monkeypatch.setattr(offline_agent, "_emit_offline_packet", lambda *a, **kw: None)
    monkeypatch.setattr(
        offline_agent,
        "credential_status_for_slug",
        lambda *a, **kw: CredentialStatus(available=seen["available"], source=None, looked_for=()),
    )

    class Agent:
        name = "claude"

        async def install(self) -> None:
            pass

        async def run(self, ctx: Any) -> AgentResult:
            seen["models"].append(ctx.resolved_model)
            assert ctx.tool_state.terminal_submission is None
            assert ctx.tool_state.output is None
            ctx.tool_state.output = "attempt output"
            return seen["results"].get(
                ctx.resolved_model, AgentResult(success=True, terminal_submission_received=True)
            )

    monkeypatch.setattr(offline_agent, "resolve_runtime_agent", lambda **_: Agent())
    # Keep catalog alias resolution real, and identify the concrete IDs in assertions.
    patch = tmp_path / "diff.patch"
    patch.write_text("diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-a\n+b\n")
    seen["materialization"] = DiffMaterialization(
        path=patch, base_ref="HEAD", line_count=6, empty=False
    )
    seen["settings"] = RepoSettings(models=[PRIMARY, BACKUP])
    return seen


async def run(dispatch: dict[str, Any], tmp_path: Path, model: str | None = None) -> Any:
    return await offline_agent.run_offline_agent_review(
        cwd=tmp_path,
        materialization=dispatch["materialization"],
        prompt="review",
        model=model,
        tmpdir=tmp_path,
    )


@pytest.mark.parametrize("override", ["config", "explicit", "env"])
async def test_offline_model_precedence(
    dispatch: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, override: str
) -> None:
    if override == "env":
        monkeypatch.setenv("MERGECRAFT_MODEL", BACKUP)
    elif override == "explicit":
        monkeypatch.setenv("MERGECRAFT_MODEL", PRIMARY)
    result = await run(dispatch, tmp_path, BACKUP if override == "explicit" else None)
    expected = PRIMARY if override == "config" else BACKUP
    assert result.success, result.error
    assert dispatch["models"] == [
        offline_agent.resolve_model(slug=expected, respect_env_override=False)
    ]


@pytest.mark.parametrize(
    ("retryable", "allow", "pin"),
    [(True, True, False), (False, True, False), (True, False, False), (True, True, True)],
)
async def test_offline_model_fallback_policy(
    dispatch: dict[str, Any], tmp_path: Path, retryable: bool, allow: bool, pin: bool
) -> None:
    dispatch["settings"] = RepoSettings(
        models=[PRIMARY, BACKUP], allow_fallback=allow, model_pin=pin
    )
    primary = offline_agent.resolve_model(slug=PRIMARY, respect_env_override=False)
    dispatch["results"][primary] = AgentResult(
        success=False, error="provider unavailable", metadata={"retryable": retryable}
    )
    result = await run(dispatch, tmp_path)
    assert result.success is (retryable and allow and not pin)
    if not allow:
        assert result.outcome == RunOutcome.configuration_error
    if result.success:
        assert len(dispatch["models"]) == 2
    else:
        assert set(dispatch["models"]) == {primary}


async def test_offline_no_credentials_never_dispatches(
    dispatch: dict[str, Any], tmp_path: Path
) -> None:
    dispatch["available"] = False
    result = await run(dispatch, tmp_path)
    assert not result.success
    assert "credential" in result.error
    assert dispatch["models"] == []


async def test_offline_process_success_without_terminal_is_inconclusive(
    dispatch: dict[str, Any], tmp_path: Path
) -> None:
    dispatch["settings"] = RepoSettings(models=[PRIMARY], model_pin=True)
    primary = offline_agent.resolve_model(slug=PRIMARY, respect_env_override=False)
    dispatch["results"][primary] = AgentResult(success=True)
    result = await run(dispatch, tmp_path)
    assert not result.success
    assert result.outcome == RunOutcome.inconclusive


async def test_offline_empty_model_chain_is_configuration_error(
    dispatch: dict[str, Any], tmp_path: Path
) -> None:
    dispatch["settings"] = RepoSettings()
    result = await run(dispatch, tmp_path)
    assert result.outcome == RunOutcome.configuration_error
    assert dispatch["models"] == []


async def test_offline_real_resolver_cross_harness_and_credential_status(
    dispatch: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from mergecraft.modes import compute_modes
    from mergecraft.utils import agent_resolve

    monkeypatch.setattr(offline_agent, "resolve_runtime_agent", agent_resolve.resolve_runtime_agent)
    monkeypatch.setattr(
        offline_agent, "credential_status_for_slug", agent_resolve.credential_status_for_slug
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")
    monkeypatch.delenv("MERGECRAFT_AGENT", raising=False)
    seen: list[str] = []

    async def install(_token: str | None = None) -> str:
        return "stub"

    async def claude_run(ctx: Any) -> AgentResult:
        seen.append("claude")
        assert ctx.tool_state.modes == compute_modes("claude", signed_commits=False)
        return AgentResult(
            success=False, error="temporary provider failure", metadata={"retryable": True}
        )

    async def codex_run(ctx: Any) -> AgentResult:
        seen.append("codex")
        assert ctx.tool_state.modes == compute_modes("codex", signed_commits=False)
        return AgentResult(success=True, terminal_submission_received=True)

    monkeypatch.setattr(
        agent_resolve,
        "agents",
        {
            "claude": replace(agent_resolve.agents["claude"], _install=install, _run=claude_run),
            "codex": replace(agent_resolve.agents["codex"], _install=install, _run=codex_run),
        },
    )
    for slug in (PRIMARY, BACKUP):
        assert agent_resolve.credential_status_for_slug(
            slug, settings=dispatch["settings"], cwd=tmp_path, wired=True
        ).available
    result = await run(dispatch, tmp_path)
    assert result.success, result.error
    assert seen == ["claude", "codex"]


async def test_offline_missing_fallback_discards_prior_output(
    dispatch: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = offline_agent.resolve_model(slug=PRIMARY, respect_env_override=False)
    dispatch["results"][primary] = AgentResult(
        success=False, error="temporary failure", metadata={"retryable": True}
    )
    monkeypatch.setattr(
        offline_agent,
        "credential_status_for_slug",
        lambda slug, **kw: CredentialStatus(available=slug == PRIMARY, source=None, looked_for=()),
    )
    result = await run(dispatch, tmp_path)
    assert not result.success
    assert result.structured_output is None
    assert dispatch["models"] == [primary]


async def test_offline_residency_rejection_never_dispatches(
    dispatch: dict[str, Any], tmp_path: Path
) -> None:
    from mergecraft.enterprise.controls import EnterpriseSettings
    from mergecraft.enterprise.runtime import bind_enterprise_from_settings

    dispatch["settings"] = RepoSettings(
        models=[PRIMARY], enterprise=EnterpriseSettings(allowed_regions=("eu-west-1",))
    )
    try:
        result = await run(dispatch, tmp_path)
        assert not result.success
        assert "permitted" in result.error or "residency" in result.error
        assert dispatch["models"] == []
    finally:
        bind_enterprise_from_settings(EnterpriseSettings())


async def test_offline_fallback_budget_is_cumulative(
    dispatch: dict[str, Any], tmp_path: Path
) -> None:
    from dataclasses import replace

    from mergecraft.agents.shared import AgentUsage
    from mergecraft.utils.run_bounds import resolve_run_bounds

    for slug in (PRIMARY, BACKUP):
        model = offline_agent.resolve_model(slug=slug, respect_env_override=False)
        dispatch["results"][model] = AgentResult(
            success=slug == BACKUP,
            error="temporary" if slug == PRIMARY else None,
            metadata={"retryable": True},
            usage=AgentUsage(agent="claude", input_tokens=6, output_tokens=0),
            terminal_submission_received=slug == BACKUP,
        )
    bounds = replace(
        resolve_run_bounds(settings=dispatch["settings"]), token_budget=10, token_budget_tolerance=0
    )
    result = await offline_agent.run_offline_agent_review(
        cwd=tmp_path,
        materialization=dispatch["materialization"],
        prompt="review",
        model=None,
        tmpdir=tmp_path,
        run_bounds=bounds,
    )
    assert not result.success
    assert len(dispatch["models"]) == 2
    assert "budget" in result.error.lower()
