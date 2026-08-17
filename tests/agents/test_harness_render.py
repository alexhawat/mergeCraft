"""AP2 harness render suite — registry-driven subagent config per driver.

Wave plan: ``.ignorelocal/03-agent-pipeline-wave-plan.md`` (PR AP2).
Covers ``mergecraft.agents.harness_render`` — ``render_agents`` projects
selected registry bindings into each harness shape (Claude ``agents.json``,
OpenCode subagent blocks, Codex/Gemini/Cursor subagent dispatch or declared
degradation). Locked decisions: **D2** (only routed agents render),
**D4** (unrenderable bindings fail loudly), **D5** (Codex degradation is
declared in run metadata, not hidden).

AP2.1: seven tests; reconciled post-AP2.2 — all pass with no xfail markers.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING

import pytest

from mergecraft.agents.claude import build_agents_json
from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.agents.verifier import verifier_denied_tool_names
from mergecraft.config.settings import load_repo_settings
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.types import REVIEWER_AGENT_NAME, VERIFIER_AGENT_NAME
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

    from mergecraft.agents.registry import Registry

_DEFAULT_MODELS_YAML = """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
  - google/gemini-3.1-pro-preview
"""


def _stub_slug_runnability(monkeypatch: MonkeyPatch) -> None:
    """Deterministic model-chain resolution without live credentials or binaries."""
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve.has_credentials_for_slug",
        lambda _slug: True,
    )
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._agent_binary_available",
        lambda _slug: True,
    )


def _write_config(tmp_path: Path, body: str) -> None:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(body.strip() + "\n", encoding="utf-8")


def _tool_ctx(tmp_path: Path) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request"),
            shell="restricted",
            push="restricted",
        ),
        github=GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="http://127.0.0.1:0/mcp",
        tmpdir=str(tmp_path),
        signed_commits=True,
        xrepo=None,
        static_checks_enabled=True,
    )


def _load_registry(tmp_path: Path) -> Registry:
    from mergecraft.agents.registry import load_registry

    settings = load_repo_settings(root=tmp_path)
    return load_registry(settings=settings, repo_root=tmp_path)


def test_claude_agents_json_renders_from_registry(tmp_path: Path) -> None:
    """Production ``render_agents(..., harness="claude")`` must match legacy bytes."""
    from mergecraft.agents.harness_render import default_subagent_selection, render_agents

    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    ctx = _tool_ctx(tmp_path)
    denied_verifier = verifier_denied_tool_names(ctx)
    denied_reviewer = subagent_denied_tool_names(ctx)
    registry = _load_registry(tmp_path)
    result = render_agents(
        registry,
        selected=default_subagent_selection(registry),
        harness="claude",
        ctx=ctx,
    )
    legacy = build_agents_json(
        verifier_denied_tools=denied_verifier,
        subagent_denied_tools=denied_reviewer,
    )
    assert result.payload == legacy


def test_opencode_subagents_carry_per_agent_models(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """P4 — OpenCode subagent blocks carry each binding's dispatched model."""
    from mergecraft.agents.harness_render import HarnessRenderResult, render_agents
    from mergecraft.agents.registry import resolve_agent_model

    _stub_slug_runnability(monkeypatch)

    body = (
        _DEFAULT_MODELS_YAML
        + """
agents:
  reviewer:
    model: anthropic/claude-sonnet
  verifier:
    model: openai/gpt-5.3-codex
"""
    )
    _write_config(tmp_path, body)
    registry = _load_registry(tmp_path)
    settings = load_repo_settings(root=tmp_path)
    ctx = _tool_ctx(tmp_path)
    reviewer_binding = registry.resolve_role("reviewer")
    verifier_binding = registry.resolve_role("verifier")
    reviewer_model = resolve_agent_model(reviewer_binding, settings=settings).dispatched_model
    verifier_model = resolve_agent_model(verifier_binding, settings=settings).dispatched_model
    assert reviewer_model != verifier_model

    result = render_agents(
        registry,
        selected=(REVIEWER_AGENT_NAME, VERIFIER_AGENT_NAME),
        harness="opencode",
        ctx=ctx,
    )
    assert isinstance(result, HarnessRenderResult)
    config = json.loads(result.payload) if isinstance(result.payload, str) else result.payload
    agents = config["agent"]
    assert agents[REVIEWER_AGENT_NAME]["model"] == reviewer_model
    assert agents[VERIFIER_AGENT_NAME]["model"] == verifier_model


def test_codex_renders_real_subagents_or_declares_degradation(tmp_path: Path) -> None:
    """D5 — Codex either renders real subagents or records declared degradation."""
    from mergecraft.agents.codex import CODEX_SUBAGENT_DEGRADATION
    from mergecraft.agents.harness_render import HarnessRenderResult, render_agents

    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    registry = _load_registry(tmp_path)
    ctx = _tool_ctx(tmp_path)
    result = render_agents(
        registry,
        selected=(REVIEWER_AGENT_NAME, VERIFIER_AGENT_NAME),
        harness="codex",
        ctx=ctx,
    )
    assert isinstance(result, HarnessRenderResult)
    payload_text = result.payload if isinstance(result.payload, str) else json.dumps(result.payload)
    has_real_subagents = (
        REVIEWER_AGENT_NAME in payload_text
        and VERIFIER_AGENT_NAME in payload_text
        and "subagent" in payload_text.lower()
        and result.metadata.get("harness_degradations") is None
    )
    degradations = result.metadata.get("harness_degradations")
    has_declared_degradation = isinstance(degradations, list) and len(degradations) >= 1
    assert has_real_subagents or has_declared_degradation
    if has_declared_degradation:
        kinds = {entry.get("kind") for entry in degradations}
        assert CODEX_SUBAGENT_DEGRADATION.kind in kinds


def test_gemini_and_cursor_render_or_declare(tmp_path: Path) -> None:
    """Gemini and Cursor harnesses render subagents or declare degradation like Codex."""
    from mergecraft.agents.harness_render import HarnessRenderResult, render_agents

    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    registry = _load_registry(tmp_path)
    ctx = _tool_ctx(tmp_path)
    selected = (REVIEWER_AGENT_NAME, VERIFIER_AGENT_NAME)

    for harness in ("gemini", "cursor"):
        result = render_agents(
            registry,
            selected=selected,
            harness=harness,
            ctx=ctx,
        )
        assert isinstance(result, HarnessRenderResult)
        payload_text = (
            result.payload if isinstance(result.payload, str) else json.dumps(result.payload)
        )
        has_subagent_surface = (
            REVIEWER_AGENT_NAME in payload_text and VERIFIER_AGENT_NAME in payload_text
        )
        degradations = result.metadata.get("harness_degradations")
        has_declared = isinstance(degradations, list) and any(
            entry.get("harness") == harness for entry in degradations
        )
        assert has_subagent_surface or has_declared


def test_unrenderable_binding_fails_loudly(tmp_path: Path) -> None:
    """D4 — bindings a harness cannot express raise instead of silently collapsing."""
    from mergecraft.agents.harness_render import UnrenderableBindingError, render_agents

    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    registry = _load_registry(tmp_path)
    ctx = _tool_ctx(tmp_path)
    with pytest.raises(UnrenderableBindingError, match="orchestrator"):
        render_agents(
            registry,
            selected=("orchestrator",),
            harness="claude",
            ctx=ctx,
        )


def test_only_routed_agents_are_rendered(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """D2 — only the selected roster is rendered, not the full registry."""
    from mergecraft.agents.harness_render import HarnessRenderResult, render_agents

    _stub_slug_runnability(monkeypatch)

    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    registry = _load_registry(tmp_path)
    ctx = _tool_ctx(tmp_path)
    selected = ("reviewer", "verifier", "classifier")
    result = render_agents(
        registry,
        selected=selected,
        harness="claude",
        ctx=ctx,
    )
    assert isinstance(result, HarnessRenderResult)
    agents = json.loads(result.payload) if isinstance(result.payload, str) else result.payload
    assert len(agents) == 3
    rendered_ids = set(agents)
    assert REVIEWER_AGENT_NAME in rendered_ids
    assert VERIFIER_AGENT_NAME in rendered_ids
    classifier_binding = registry.resolve_role("classifier")
    assert classifier_binding.agent_id in rendered_ids
    assert registry.resolve_role("orchestrator").agent_id not in rendered_ids
    assert registry.resolve_role("judge").agent_id not in rendered_ids
    assert len(registry.all_bindings()) > len(agents)


def test_declared_degradation_reaches_the_run_manifest(tmp_path: Path) -> None:
    """Declared harness degradation must flow into run-manifest metadata."""
    from mergecraft.agents.codex import CODEX_SUBAGENT_DEGRADATION
    from mergecraft.agents.harness_render import (
        HarnessRenderResult,
        render_agents,
        run_manifest_metadata,
    )
    from mergecraft.agents.shared import AgentResult

    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    registry = _load_registry(tmp_path)
    ctx = _tool_ctx(tmp_path)
    render_result = render_agents(
        registry,
        selected=(REVIEWER_AGENT_NAME, VERIFIER_AGENT_NAME),
        harness="codex",
        ctx=ctx,
    )
    assert isinstance(render_result, HarnessRenderResult)
    manifest_meta = run_manifest_metadata(render_result)
    assert "harness_degradations" in manifest_meta
    degradations = manifest_meta["harness_degradations"]
    assert isinstance(degradations, list)
    assert degradations
    codex_entries = [entry for entry in degradations if entry.get("harness") == "codex"]
    assert codex_entries
    entry = codex_entries[0]
    assert entry["kind"] == CODEX_SUBAGENT_DEGRADATION.kind
    assert entry["toolset_parity"] is CODEX_SUBAGENT_DEGRADATION.toolset_parity
    assert set(entry) >= {"harness", "kind", "toolset_parity", "selected_agents"}

    agent_result = AgentResult(success=True)
    merged = {**(agent_result.metadata or {}), **manifest_meta}
    assert merged["harness_degradations"] == degradations
    assert asdict(CODEX_SUBAGENT_DEGRADATION)["kind"] in {
        row.get("kind") for row in merged["harness_degradations"]
    }
