"""Render registry bindings into per-harness subagent configuration (AP2).

Projects only the routed roster (D2) into each driver's native shape. Where a
harness cannot express a binding, raises :class:`UnrenderableBindingError` (D4).
Codex/Gemini/Cursor prose-only subagent paths record declared degradation in
``metadata`` for the run manifest (D5).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from mergecraft.agents.registry import (
    AgentBinding,
    AgentRole,
    Registry,
    resolve_agent_model,
    resolve_prompt_text,
)
from mergecraft.agents.shared import AgentResult, AgentRunContext
from mergecraft.agents.verifier import (
    VERIFIER_RUBRIC_VERSION,
    pinned_judge_model,
)
from mergecraft.config.settings import load_repo_settings
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.types import format_mcp_tool_ref

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mergecraft.mcp.context import ToolContext

HarnessName = Literal["claude", "opencode", "codex", "gemini", "cursor"]

_REVIEWER_DESCRIPTION = (
    "Read-only review subagent for lens-based code review. "
    "Reads only — no writes, no state-changing shell or MCP calls."
)

_VERIFIER_DESCRIPTION = (
    "Read-only verification subagent for Critical/Major analyzer, CI and "
    "agent-authored findings. Confirms, downgrades, or drops before "
    f"publication against rubric v{VERIFIER_RUBRIC_VERSION}."
)

_RECALL_DESCRIPTION = (
    "Read-only recall subagent. Receives the diff and draft findings; may only "
    "return novel findings absent from the draft list. Output is deferred-only."
)

_CLASSIFIER_DESCRIPTION = (
    "Read-only change classifier subagent. Emits a typed risk and change map for lens routing."
)

_PROSE_ONLY_HARNESSES: frozenset[HarnessName] = frozenset({"codex", "gemini", "cursor"})

_CLAUDE_UNRENDERABLE_ROLES: frozenset[AgentRole] = frozenset({AgentRole.orchestrator})


class UnrenderableBindingError(ValueError):
    """A selected binding cannot be expressed on the target harness (D4)."""


@dataclass(frozen=True, slots=True)
class HarnessRenderResult:
    """One harness projection of a routed agent roster."""

    harness: HarnessName
    payload: str | dict[str, Any]
    selected_agent_ids: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


def run_manifest_metadata(result: HarnessRenderResult) -> dict[str, Any]:
    """Return metadata merged into ``AgentResult.metadata`` / evidence manifest."""
    if not result.metadata:
        return {}
    return dict(result.metadata)


def _repo_root_from_ctx(ctx: AgentRunContext | ToolContext) -> Path | None:
    tool_state = getattr(ctx, "tool_state", None)
    if tool_state is not None:
        repo = primary_repo_state(tool_state)
        if repo.dir:
            return Path(repo.dir)
    tmpdir = getattr(ctx, "tmpdir", None)
    if tmpdir:
        return Path(tmpdir)
    return None


def _settings_for_ctx(ctx: AgentRunContext | ToolContext) -> Any:
    root = _repo_root_from_ctx(ctx)
    if root is not None:
        return load_repo_settings(root=root)
    from mergecraft.config.settings import default_settings

    return default_settings()


def _resolve_selected_bindings(
    registry: Registry,
    selected: Sequence[str],
    *,
    settings: Any | None = None,
    tool_state: Any | None = None,
) -> list[AgentBinding]:
    bindings: list[AgentBinding] = []
    role_values = {role.value for role in AgentRole}
    by_id = {binding.agent_id: binding for binding in registry.all_bindings()}
    for key in selected:
        resolved: AgentBinding
        if key in role_values:
            resolved = registry.resolve_role(key)
        elif key in by_id:
            resolved = by_id[key]
        else:
            for candidate in registry.all_bindings():
                if candidate.agent_id == key:
                    resolved = candidate
                    break
            else:
                msg = f"no registry binding for selected agent {key!r}"
                raise KeyError(msg)
        bindings.append(
            _binding_with_round_limits(
                resolved,
                settings=settings,
                tool_state=tool_state,
            )
        )
    return bindings


def _binding_with_round_limits(
    binding: AgentBinding,
    *,
    settings: Any | None,
    tool_state: Any | None,
) -> AgentBinding:
    """Apply RC12 round-scaled budget (not ``timeout_s``) to reviewer, verifier, and recall."""
    if settings is None or tool_state is None:
        return binding
    if binding.role not in (AgentRole.reviewer, AgentRole.verifier, AgentRole.recall):
        return binding
    if binding.role is AgentRole.recall and not settings.review.recall_pass:
        return binding
    from mergecraft.mcp.convergence_runtime import subagent_limits_for_round

    limits = subagent_limits_for_round(
        binding,
        settings=settings,
        tool_state=tool_state,
    )
    return binding.model_copy(update={"budget": limits.budget, "timeout_s": limits.timeout_s})


def _denied_tool_names(
    ctx: AgentRunContext | ToolContext,
    binding: AgentBinding,
) -> list[str]:
    from mergecraft.agents.gates import subagent_denied_tool_names
    from mergecraft.agents.verifier import verifier_denied_tool_names

    if isinstance(ctx, AgentRunContext):
        if binding.role in (AgentRole.verifier, AgentRole.judge):
            return list(ctx.verifier_denied_tools)
        return list(ctx.subagent_denied_tools)
    if binding.role in (AgentRole.verifier, AgentRole.judge):
        return verifier_denied_tool_names(ctx)
    return subagent_denied_tool_names(ctx)


def _strip_provider_prefix(specifier: str) -> str:
    slash = specifier.find("/")
    return specifier[slash + 1 :] if slash > 0 else specifier


def _harness_dispatched_model(binding: AgentBinding, settings: Any) -> str:
    """Return the model slug written into harness config (declared intent, not runtime pick)."""
    chain = list(binding.model_chain)
    if not chain:
        msg = f"empty model_chain on agent {binding.agent_id!r}"
        raise RuntimeError(msg)
    try:
        return resolve_agent_model(binding, settings=settings).dispatched_model
    except RuntimeError:
        return chain[0]


def _claude_harness_model(binding: AgentBinding, settings: Any) -> str:
    if binding.role is AgentRole.verifier:
        return pinned_judge_model("claude") or "claude-sonnet-5"
    if binding.role in (AgentRole.reviewer, AgentRole.recall):
        return "claude-sonnet-5"
    return _strip_provider_prefix(_harness_dispatched_model(binding, settings))


def _role_description(binding: AgentBinding) -> str:
    match binding.role:
        case AgentRole.reviewer:
            return _REVIEWER_DESCRIPTION
        case AgentRole.verifier | AgentRole.judge:
            return _VERIFIER_DESCRIPTION
        case AgentRole.recall:
            return _RECALL_DESCRIPTION
        case AgentRole.classifier:
            return _CLASSIFIER_DESCRIPTION
        case AgentRole.orchestrator:
            return "Orchestrator agent."
    return f"mergeCraft {binding.role.value} agent."


def _claude_agent_entry(
    binding: AgentBinding,
    *,
    settings: Any,
    denied_tools: Sequence[str],
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "description": _role_description(binding),
        "prompt": resolve_prompt_text(
            binding.prompt_id,
            version=binding.prompt_version,
        ),
        "model": _claude_harness_model(binding, settings),
    }
    denied = [format_mcp_tool_ref("claude", name) for name in denied_tools]
    if denied:
        entry["disallowedTools"] = denied
    return entry


def _render_claude(
    bindings: Sequence[AgentBinding],
    *,
    ctx: AgentRunContext | ToolContext,
    settings: Any,
) -> HarnessRenderResult:
    agents: dict[str, Any] = {}
    selected_ids: list[str] = []
    for binding in bindings:
        if binding.role in _CLAUDE_UNRENDERABLE_ROLES:
            msg = (
                f"claude harness cannot render orchestrator binding "
                f"{binding.agent_id!r} as a subagent (D4)"
            )
            raise UnrenderableBindingError(msg)
        denied = _denied_tool_names(ctx, binding)
        agents[binding.agent_id] = _claude_agent_entry(
            binding,
            settings=settings,
            denied_tools=denied,
        )
        selected_ids.append(binding.agent_id)
    return HarnessRenderResult(
        harness="claude",
        payload=json.dumps(agents),
        selected_agent_ids=tuple(selected_ids),
    )


def _opencode_agent_entry(
    binding: AgentBinding,
    *,
    settings: Any,
    denied_tools: Sequence[str],
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "description": _role_description(binding),
        "prompt": resolve_prompt_text(
            binding.prompt_id,
            version=binding.prompt_version,
        ),
        "mode": "subagent",
        "model": _harness_dispatched_model(binding, settings),
    }
    denied = {format_mcp_tool_ref("opencode", name): "deny" for name in denied_tools}
    if denied:
        entry["permission"] = denied
    return entry


def _render_opencode(
    bindings: Sequence[AgentBinding],
    *,
    ctx: AgentRunContext | ToolContext,
    settings: Any,
) -> HarnessRenderResult:
    agents: dict[str, Any] = {}
    selected_ids: list[str] = []
    for binding in bindings:
        denied = _denied_tool_names(ctx, binding)
        agents[binding.agent_id] = _opencode_agent_entry(
            binding,
            settings=settings,
            denied_tools=denied,
        )
        selected_ids.append(binding.agent_id)
    return HarnessRenderResult(
        harness="opencode",
        payload={"agent": agents},
        selected_agent_ids=tuple(selected_ids),
    )


def _prose_subagent_instructions(bindings: Sequence[AgentBinding]) -> str:
    parts = [
        "Registered read-only subagents (spawn via subagent tooling when needed):",
    ]
    for binding in bindings:
        parts.append(f"## {binding.agent_id}")
        parts.append(
            resolve_prompt_text(
                binding.prompt_id,
                version=binding.prompt_version,
            )
        )
    return "\n\n".join(parts)


def _degradation_row(
    harness: HarnessName,
    *,
    kind: str,
    toolset_parity: bool,
    selected_agents: Sequence[str],
) -> dict[str, Any]:
    return {
        "harness": harness,
        "kind": kind,
        "toolset_parity": toolset_parity,
        "selected_agents": list(selected_agents),
    }


def _render_prose_only(
    harness: HarnessName,
    bindings: Sequence[AgentBinding],
) -> HarnessRenderResult:
    from mergecraft.agents.codex import CODEX_SUBAGENT_DEGRADATION

    selected_ids = tuple(binding.agent_id for binding in bindings)
    instructions = _prose_subagent_instructions(bindings)
    degradation = _degradation_row(
        harness,
        kind=CODEX_SUBAGENT_DEGRADATION.kind,
        toolset_parity=CODEX_SUBAGENT_DEGRADATION.toolset_parity,
        selected_agents=selected_ids,
    )
    return HarnessRenderResult(
        harness=harness,
        payload=instructions,
        selected_agent_ids=selected_ids,
        metadata={"harness_degradations": [degradation]},
    )


def render_agents(
    registry: Registry,
    *,
    selected: Sequence[str],
    harness: HarnessName | str,
    ctx: AgentRunContext | ToolContext,
) -> HarnessRenderResult:
    """Project ``selected`` registry bindings into ``harness`` config (D2)."""
    harness_name: HarnessName = harness  # type: ignore[assignment]  # — harness is HarnessName | str; callers pass a valid HarnessName literal
    settings = _settings_for_ctx(ctx)
    tool_state = getattr(ctx, "tool_state", None)
    bindings = _resolve_selected_bindings(
        registry,
        selected,
        settings=settings,
        tool_state=tool_state,
    )

    if harness_name == "claude":
        return _render_claude(bindings, ctx=ctx, settings=settings)
    if harness_name == "opencode":
        return _render_opencode(bindings, ctx=ctx, settings=settings)
    if harness_name in _PROSE_ONLY_HARNESSES:
        return _render_prose_only(harness_name, bindings)

    msg = f"unknown harness {harness!r}"
    raise ValueError(msg)


def default_subagent_selection(
    registry: Registry,
    *,
    recall_pass: bool = False,
) -> tuple[str, ...]:
    """Default routed roster before AP4 lens routing — reviewer + verifier (+ recall)."""
    reviewer = registry.resolve_role(AgentRole.reviewer)
    verifier = registry.resolve_role(AgentRole.verifier)
    roster: list[str] = [reviewer.agent_id, verifier.agent_id]
    if recall_pass:
        recall = registry.resolve_role(AgentRole.recall)
        roster.append(recall.agent_id)
    return tuple(roster)


def render_for_run(
    ctx: AgentRunContext,
    harness: HarnessName,
    *,
    selected: Sequence[str] | None = None,
) -> HarnessRenderResult:
    """Load the repo registry and render the routed roster for one agent run."""
    from mergecraft.agents.registry import load_registry

    root = _repo_root_from_ctx(ctx) or Path(ctx.tmpdir)
    settings = load_repo_settings(root=root)
    registry = load_registry(settings=settings, repo_root=root)
    roster = (
        tuple(selected)
        if selected is not None
        else default_subagent_selection(registry, recall_pass=settings.review.recall_pass)
    )
    return render_agents(registry, selected=roster, harness=harness, ctx=ctx)


def merge_manifest_metadata(
    result: AgentResult,
    render_result: HarnessRenderResult,
) -> AgentResult:
    """Merge harness degradation metadata into an ``AgentResult``."""
    from dataclasses import replace

    manifest_meta = run_manifest_metadata(render_result)
    if not manifest_meta:
        return result
    meta = dict(result.metadata or {})
    meta.update(manifest_meta)
    return replace(result, metadata=meta)


__all__ = [
    "HarnessRenderResult",
    "UnrenderableBindingError",
    "default_subagent_selection",
    "merge_manifest_metadata",
    "render_agents",
    "render_for_run",
    "run_manifest_metadata",
]
