"""AP1 agent registry suite — binding model, prompt, toolset and budget.

Wave plan: ``.ignorelocal/03-agent-pipeline-wave-plan.md`` (PR AP1).
Covers ``mergecraft.agents.registry`` — frozen ``AgentBinding``, ``Registry``
loading defaults + ``.mergecraft/config.yaml`` overrides, per-agent chain
resolution reusing ``pick_runnable_slug_from_chain``, and ``resolve_agent_model``
recording the executed slug (D4). Reconciled green after AP1.2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import pytest

from mergecraft.agents.reviewer import REVIEWER_SYSTEM_PROMPT
from mergecraft.agents.verifier import VERIFIER_SYSTEM_PROMPT, pinned_judge_model
from mergecraft.config.settings import load_repo_settings
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.shared import ToolClass, ToolSpec
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.types import XrepoConfig
from mergecraft.utils.agent_resolve import effective_model_chain
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_ROLES: tuple[str, ...] = (
    "orchestrator",
    "reviewer",
    "verifier",
    "judge",
    "classifier",
)

_TERMINAL_PROTOCOL_TOOL = "submit_review_verdict"

_DEFAULT_MODELS_YAML = """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
  - google/gemini-3.1-pro-preview
"""


def _write_config(tmp_path: Path, body: str) -> None:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(body.strip() + "\n", encoding="utf-8")


def _tool_ctx(
    tmp_path: Path,
    *,
    shell: Literal["disabled", "restricted", "enabled"] = "restricted",
    push: Literal["disabled", "restricted", "enabled"] = "restricted",
) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="unknown"),
            shell=shell,
            push=push,
        ),
        github=GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        signed_commits=True,
        xrepo=XrepoConfig(mode="explicit", read=["other"], write=["other"]),
        static_checks_enabled=True,
    )


def _load_registry(tmp_path: Path) -> object:
    from mergecraft.agents.registry import load_registry

    settings = load_repo_settings(root=tmp_path)
    return load_registry(settings=settings, repo_root=tmp_path)


def _resolve_role(registry: object, role: str) -> object:
    from mergecraft.agents.registry import AgentRole

    resolve = registry.resolve_role
    return resolve(AgentRole(role))


def _tool_names(registry: object, binding: object, ctx: ToolContext) -> frozenset[str]:
    resolve_tool_names = registry.resolve_tool_names
    names = resolve_tool_names(binding, ctx)
    return frozenset(names)


def _class_names(specs: list[ToolSpec]) -> frozenset[str]:
    return frozenset(str(spec.tool_class) for spec in specs)


def test_agent_chain_defaults_to_the_run_chain(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Compatibility pin: the run-level chain is ``effective_model_chain`` (today's behaviour).

    AP1.2 must default every agent binding's ``model_chain`` to this chain when
    the operator supplies no per-agent override.
    """
    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    monkeypatch.chdir(tmp_path)
    settings = load_repo_settings(root=tmp_path)
    expected = [
        "anthropic/claude-sonnet",
        "openai/gpt-5.3-codex",
        "google/gemini-3.1-pro-preview",
    ]
    assert effective_model_chain(settings) == expected


def test_every_role_resolves_to_a_binding(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Each core role — orchestrator, reviewer, verifier, judge, classifier — has a binding."""
    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    monkeypatch.chdir(tmp_path)
    registry = _load_registry(tmp_path)

    for role in _ROLES:
        binding = _resolve_role(registry, role)
        assert binding.role.value == role
        assert binding.agent_id
        assert binding.model_chain
        assert binding.prompt_id
        assert binding.prompt_version
        assert binding.tool_classes


def test_reviewer_and_verifier_have_different_toolsets(tmp_path: Path) -> None:
    """P2 regression pin — reviewer and verifier tool-name sets must differ via the registry."""
    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    registry = _load_registry(tmp_path)
    ctx = _tool_ctx(tmp_path)

    reviewer = _resolve_role(registry, "reviewer")
    verifier = _resolve_role(registry, "verifier")
    reviewer_names = _tool_names(registry, reviewer, ctx)
    verifier_names = _tool_names(registry, verifier, ctx)

    assert reviewer_names, "reviewer toolset must not be empty"
    assert verifier_names, "verifier toolset must not be empty"
    assert reviewer_names != verifier_names, (
        "reviewer and verifier must not share an identical tool-name set (P2)"
    )
    assert "checkout_pr" in reviewer_names
    assert "checkout_pr" not in verifier_names
    assert "verify_agent_findings" in verifier_names
    assert "verify_agent_findings" not in reviewer_names


def test_per_agent_model_chain_falls_back(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """P3/D3 — an agent's own fallback runs when its primary slug is unavailable."""
    _write_config(
        tmp_path,
        _DEFAULT_MODELS_YAML
        + """
agents:
  reviewer:
    modelChain:
      - anthropic/claude-opus
      - anthropic/claude-sonnet
""",
    )
    monkeypatch.chdir(tmp_path)
    from mergecraft.agents.registry import resolve_agent_model

    registry = _load_registry(tmp_path)
    binding = _resolve_role(registry, "reviewer")
    settings = load_repo_settings(root=tmp_path)

    unavailable_primary = "anthropic/claude-opus"
    fallback = "anthropic/claude-sonnet"

    def _runnable(slug: str) -> bool:
        return slug == fallback

    resolved = resolve_agent_model(
        binding,
        settings=settings,
        slug_runnable=_runnable,
    )
    assert resolved.requested_model == unavailable_primary
    assert resolved.executed_model == fallback


def test_executed_model_is_recorded_not_requested(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """D4 — the executed slug is recorded, never the unavailable requested head."""
    _write_config(
        tmp_path,
        _DEFAULT_MODELS_YAML
        + """
agents:
  reviewer:
    modelChain:
      - anthropic/claude-opus
      - openai/gpt-5.3-codex
""",
    )
    monkeypatch.chdir(tmp_path)
    from mergecraft.agents.registry import resolve_agent_model

    registry = _load_registry(tmp_path)
    binding = _resolve_role(registry, "reviewer")
    settings = load_repo_settings(root=tmp_path)

    requested = "anthropic/claude-opus"
    executed = "openai/gpt-5.3-codex"

    resolved = resolve_agent_model(
        binding,
        settings=settings,
        slug_runnable=lambda slug: slug == executed,
    )
    assert resolved.requested_model == requested
    assert resolved.executed_model == executed
    assert resolved.executed_model != resolved.requested_model
    assert resolved.recorded_model == executed


def test_verifier_pin_invariant_survives_fallback(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """#45 — the recorded judge model always matches the dispatched verifier slug."""
    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    monkeypatch.chdir(tmp_path)
    from mergecraft.agents.registry import resolve_agent_model

    registry = _load_registry(tmp_path)
    verifier = _resolve_role(registry, "verifier")
    settings = load_repo_settings(root=tmp_path)
    pinned = pinned_judge_model("claude")
    assert pinned is not None
    assert verifier.model_chain[0] == pinned

    backup = "openai/gpt-5.3-codex"
    chain = list(verifier.model_chain)
    assert len(chain) >= 2, "verifier must carry its own fallback chain (#45 / D3)"
    assert backup in chain[1:], f"expected {backup!r} in verifier fallback tail, got {chain!r}"

    resolved = resolve_agent_model(
        verifier,
        settings=settings,
        slug_runnable=lambda slug: slug == backup,
    )
    assert resolved.requested_model == pinned
    assert resolved.executed_model != pinned
    assert resolved.recorded_model == resolved.executed_model
    assert resolved.dispatched_model == resolved.executed_model


def test_prompt_id_and_version_are_bound(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Each binding carries a prompt id/version that resolves to the live prompt text."""
    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    monkeypatch.chdir(tmp_path)
    from mergecraft.agents.registry import resolve_prompt_text

    registry = _load_registry(tmp_path)
    reviewer = _resolve_role(registry, "reviewer")
    verifier = _resolve_role(registry, "verifier")

    assert resolve_prompt_text(reviewer.prompt_id, version=reviewer.prompt_version) == (
        REVIEWER_SYSTEM_PROMPT
    )
    assert resolve_prompt_text(verifier.prompt_id, version=verifier.prompt_version) == (
        VERIFIER_SYSTEM_PROMPT
    )
    assert reviewer.prompt_id != verifier.prompt_id


def test_toolset_derives_from_tool_classes(tmp_path: Path) -> None:
    """HA4 integration — registry tool names are the class-filtered MCP surface."""
    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    registry = _load_registry(tmp_path)
    ctx = _tool_ctx(tmp_path)
    reviewer = _resolve_role(registry, "reviewer")

    from mergecraft.mcp.server import build_reviewer_tools

    expected_specs = build_reviewer_tools(ctx)
    expected_names = {spec.name for spec in expected_specs}
    expected_classes = _class_names(expected_specs)

    derived_names = _tool_names(registry, reviewer, ctx)
    assert derived_names == expected_names

    declared_classes = frozenset(str(cls) for cls in reviewer.tool_classes)
    assert declared_classes == expected_classes
    assert ToolClass.SCOPE in reviewer.tool_classes
    assert ToolClass.VERIFICATION not in reviewer.tool_classes


def test_no_read_only_agent_gets_a_terminal_protocol_tool(tmp_path: Path) -> None:
    """Read-only roles must never receive ``terminal-protocol`` tools."""
    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    registry = _load_registry(tmp_path)
    ctx = _tool_ctx(tmp_path)

    for role in ("reviewer", "verifier", "classifier"):
        binding = _resolve_role(registry, role)
        names = _tool_names(registry, binding, ctx)
        assert _TERMINAL_PROTOCOL_TOOL not in names, f"{role} received terminal protocol tool"


def test_per_agent_budget_and_timeout_apply(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Per-agent ``budget`` and ``timeout_s`` overrides apply from config."""
    _write_config(
        tmp_path,
        _DEFAULT_MODELS_YAML
        + """
agents:
  reviewer:
    budget: 5
    timeoutS: 120
""",
    )
    monkeypatch.chdir(tmp_path)
    from mergecraft.agents.registry import effective_agent_limits

    registry = _load_registry(tmp_path)
    reviewer = _resolve_role(registry, "reviewer")
    settings = load_repo_settings(root=tmp_path)

    assert reviewer.budget == 5
    assert reviewer.timeout_s == 120

    limits = effective_agent_limits(reviewer, settings=settings)
    assert limits.budget == 5
    assert limits.timeout_s == 120


def test_registry_validation_rejects_a_missing_model(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Validation fails when a binding references an unknown model slug."""
    _write_config(
        tmp_path,
        _DEFAULT_MODELS_YAML
        + """
agents:
  reviewer:
    modelChain:
      - not-a-real-mergecraft-model
""",
    )
    monkeypatch.chdir(tmp_path)
    from mergecraft.agents.registry import RegistryValidationError

    registry = _load_registry(tmp_path)
    with pytest.raises(RegistryValidationError, match=r"(?i)model|slug|unknown|unresolvable"):
        registry.validate()


def test_registry_validation_rejects_an_unknown_prompt_id(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Validation fails when ``prompt_id`` is not in the prompt catalog."""
    _write_config(
        tmp_path,
        _DEFAULT_MODELS_YAML
        + """
agents:
  reviewer:
    promptId: not.a.real.prompt.id
""",
    )
    monkeypatch.chdir(tmp_path)
    from mergecraft.agents.registry import RegistryValidationError

    registry = _load_registry(tmp_path)
    with pytest.raises(RegistryValidationError, match=r"(?i)prompt"):
        registry.validate()


def test_registry_validation_rejects_an_unreachable_lens(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Validation fails when a lens binding references an id absent from the registry."""
    _write_config(
        tmp_path,
        _DEFAULT_MODELS_YAML
        + """
agents:
  lens-security:
    lens: security
    role: reviewer
""",
    )
    monkeypatch.chdir(tmp_path)
    from mergecraft.agents.registry import RegistryValidationError

    registry = _load_registry(tmp_path)
    with pytest.raises(RegistryValidationError, match=r"(?i)lens|unreachable|unknown"):
        registry.validate()
