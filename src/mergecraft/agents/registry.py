"""Agent registry — model, prompt, toolset and budget per role and lens (AP1).

Loads bundled defaults plus ``.mergecraft/config.yaml`` overrides. Per-agent
model chains reuse :func:`mergecraft.utils.agent_resolve.effective_model_chain`
and :func:`pick_runnable_slug_from_chain` (D3).
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict

from mergecraft.agents.reviewer import REVIEWER_SYSTEM_PROMPT
from mergecraft.agents.structured_handoff import agent_finding_output_schema_id
from mergecraft.agents.verifier import VERIFIER_SYSTEM_PROMPT, pinned_judge_model
from mergecraft.config.settings import AgentBindingOverride, DispatchMode  # noqa: TC001
from mergecraft.mcp.server import build_orchestrator_tools
from mergecraft.mcp.shared import (
    REVIEWER_ALLOWED_TOOL_CLASSES,
    VERIFIER_ALLOWED_TOOL_CLASSES,
    ToolClass,
    admits_readonly_role,
)
from mergecraft.models import AUTO_EFFICIENT, MODEL_ALIASES, resolve_display_alias
from mergecraft.types import REVIEWER_AGENT_NAME, VERIFIER_AGENT_NAME
from mergecraft.utils.agent_resolve import effective_model_chain, pick_runnable_slug_from_chain

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mergecraft.config.settings import RepoSettings
    from mergecraft.mcp.context import ToolContext

_DEFAULT_BUDGET: Final[int] = 8
_DEFAULT_TIMEOUT_S: Final[int] = 600
_DEFAULT_PROMPT_VERSION: Final[str] = "1.0.0"

_PROMPT_CATALOG: Final[dict[str, tuple[str, str]]] = {
    "mergecraft.reviewer": (REVIEWER_SYSTEM_PROMPT, _DEFAULT_PROMPT_VERSION),
    "mergecraft.verifier": (VERIFIER_SYSTEM_PROMPT, _DEFAULT_PROMPT_VERSION),
    "mergecraft.orchestrator": ("", _DEFAULT_PROMPT_VERSION),
    "mergecraft.judge": (VERIFIER_SYSTEM_PROMPT, _DEFAULT_PROMPT_VERSION),
    "mergecraft.classifier": ("", _DEFAULT_PROMPT_VERSION),
}

# Lenses ship in AP5 — until then the set is empty and any lens binding fails validation.
_KNOWN_LENS_IDS: Final[frozenset[str]] = frozenset()

_ORCHESTRATOR_TOOL_CLASSES: Final[frozenset[ToolClass]] = frozenset(ToolClass)


class AgentRole(StrEnum):
    orchestrator = "orchestrator"
    reviewer = "reviewer"
    verifier = "verifier"
    judge = "judge"
    classifier = "classifier"


class RegistryValidationError(ValueError):
    """Raised when a registry binding fails structural validation."""


class AgentBinding(BaseModel):
    """Frozen resolved identity for one agent role or lens."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str
    role: AgentRole
    lens: str | None = None
    model_chain: tuple[str, ...]
    prompt_id: str
    prompt_version: str
    tool_classes: frozenset[ToolClass]
    budget: int
    timeout_s: int
    dispatch: DispatchMode = "single"
    output_schema: str | None = None


class ResolvedAgentModel(BaseModel):
    """Per-agent model resolution with executed-model recording (D4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requested_model: str
    executed_model: str
    recorded_model: str
    dispatched_model: str


class AgentLimits(BaseModel):
    """Effective budget and timeout for one binding."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    budget: int
    timeout_s: int


def resolve_prompt_text(prompt_id: str, *, version: str | None = None) -> str:
    """Return the prompt body for ``prompt_id`` at ``version`` (or latest)."""
    entry = _PROMPT_CATALOG.get(prompt_id)
    if entry is None:
        msg = f"unknown prompt id: {prompt_id!r}"
        raise KeyError(msg)
    text, catalog_version = entry
    if version is not None and version != catalog_version:
        msg = f"unknown prompt version {version!r} for {prompt_id!r}"
        raise KeyError(msg)
    return text


def _model_reference_valid(ref: str) -> bool:
    if resolve_display_alias(ref) is not None:
        return True
    pinned = pinned_judge_model("claude")
    if pinned is not None and ref == pinned:
        return True
    return any(alias.resolve == ref for alias in MODEL_ALIASES)


def _parse_role(value: str) -> AgentRole | None:
    try:
        return AgentRole(value)
    except ValueError:
        return None


def _default_model_chain(settings: RepoSettings, *, role: AgentRole) -> list[str]:
    run_chain = effective_model_chain(settings)
    if not run_chain:
        run_chain = [AUTO_EFFICIENT]
    if role is AgentRole.verifier:
        pinned = pinned_judge_model("claude")
        if pinned is None:
            return run_chain
        tail = [entry for entry in run_chain if entry != pinned]
        return [pinned, *tail]
    return run_chain


def _default_tool_classes(role: AgentRole) -> frozenset[ToolClass]:
    match role:
        case AgentRole.orchestrator:
            return _ORCHESTRATOR_TOOL_CLASSES
        case AgentRole.reviewer:
            return REVIEWER_ALLOWED_TOOL_CLASSES
        case AgentRole.verifier | AgentRole.judge:
            return VERIFIER_ALLOWED_TOOL_CLASSES
        case AgentRole.classifier:
            return frozenset(
                {
                    ToolClass.SCOPE,
                    ToolClass.REPOSITORY_READ,
                    ToolClass.ANALYSIS,
                }
            )


def _default_agent_id(role: AgentRole) -> str:
    match role:
        case AgentRole.reviewer:
            return REVIEWER_AGENT_NAME
        case AgentRole.verifier:
            return VERIFIER_AGENT_NAME
        case AgentRole.orchestrator:
            return "mergecraft-orchestrator"
        case AgentRole.judge:
            return "mergecraft-judge"
        case AgentRole.classifier:
            return "mergecraft-classifier"


def _default_prompt_id(role: AgentRole) -> str:
    return f"mergecraft.{role.value}"


def _default_output_schema(role: AgentRole) -> str | None:
    if role is AgentRole.reviewer:
        return agent_finding_output_schema_id()
    return None


def _build_default_binding(settings: RepoSettings, role: AgentRole) -> AgentBinding:
    return AgentBinding(
        agent_id=_default_agent_id(role),
        role=role,
        lens=None,
        model_chain=tuple(_default_model_chain(settings, role=role)),
        prompt_id=_default_prompt_id(role),
        prompt_version=_DEFAULT_PROMPT_VERSION,
        tool_classes=_default_tool_classes(role),
        budget=_DEFAULT_BUDGET,
        timeout_s=_DEFAULT_TIMEOUT_S,
        output_schema=_default_output_schema(role),
    )


def _apply_override(
    base: AgentBinding,
    override: AgentBindingOverride,
    *,
    agent_key: str,
    settings: RepoSettings,
) -> AgentBinding:
    role = AgentRole(override.role) if override.role is not None else base.role
    model_chain = (
        tuple(override.model_chain) if override.model_chain is not None else base.model_chain
    )
    if override.model is not None and override.model_chain is None:
        model_chain = (override.model, *tuple(base.model_chain))
    return AgentBinding(
        agent_id=agent_key if agent_key not in {r.value for r in AgentRole} else base.agent_id,
        role=role,
        lens=override.lens if override.lens is not None else base.lens,
        model_chain=model_chain,
        prompt_id=override.prompt_id or base.prompt_id,
        prompt_version=override.prompt_version or base.prompt_version,
        tool_classes=base.tool_classes,
        budget=override.budget if override.budget is not None else base.budget,
        timeout_s=override.timeout_s if override.timeout_s is not None else base.timeout_s,
        dispatch=override.dispatch or base.dispatch,
        output_schema=base.output_schema,
    )


class Registry:
    """Resolved agent roster for one repo configuration."""

    def __init__(self, bindings: dict[str, AgentBinding]) -> None:
        self._bindings = bindings
        self._by_role: dict[AgentRole, AgentBinding] = {}
        for binding in bindings.values():
            if binding.lens is None:
                self._by_role[binding.role] = binding

    def resolve_role(self, role: AgentRole | str) -> AgentBinding:
        key = AgentRole(role) if isinstance(role, str) else role
        try:
            return self._by_role[key]
        except KeyError as exc:
            msg = f"no binding for role {key!r}"
            raise KeyError(msg) from exc

    def resolve_tool_names(self, binding: AgentBinding, ctx: ToolContext) -> list[str]:
        tools = build_orchestrator_tools(ctx)
        if binding.role is AgentRole.orchestrator:
            return [spec.name for spec in tools]
        return [spec.name for spec in tools if admits_readonly_role(spec, binding.tool_classes)]

    def all_bindings(self) -> tuple[AgentBinding, ...]:
        return tuple(self._bindings.values())

    def validate(self) -> None:
        for binding in self._bindings.values():
            if not binding.model_chain:
                msg = f"agent {binding.agent_id!r} has empty model_chain"
                raise RegistryValidationError(msg)
            for slug in binding.model_chain:
                if not _model_reference_valid(slug):
                    msg = f"unresolvable model slug {slug!r} on agent {binding.agent_id!r}"
                    raise RegistryValidationError(msg)
            if binding.prompt_id not in _PROMPT_CATALOG:
                msg = f"unknown prompt id {binding.prompt_id!r} on agent {binding.agent_id!r}"
                raise RegistryValidationError(msg)
            if binding.lens is not None and binding.lens not in _KNOWN_LENS_IDS:
                msg = (
                    f"unreachable lens {binding.lens!r} on agent {binding.agent_id!r} "
                    "(lens not in registry)"
                )
                raise RegistryValidationError(msg)
            if binding.role is not AgentRole.orchestrator:
                terminal = "submit_review_verdict"
                if terminal in binding.tool_classes:
                    msg = f"read-only agent {binding.agent_id!r} holds terminal-protocol tool"
                    raise RegistryValidationError(msg)


def load_registry(
    *,
    settings: RepoSettings,
    repo_root: Path | None = None,
) -> Registry:
    """Load defaults merged with ``settings.agents`` overrides."""
    del repo_root  # reserved for future repo-local agent manifests (AP5)
    bindings: dict[str, AgentBinding] = {}
    for role in AgentRole:
        bindings[role.value] = _build_default_binding(settings, role)

    for agent_key, override in settings.agents.items():
        key_role = _parse_role(agent_key)
        declared_role = _parse_role(override.role) if override.role is not None else None
        if key_role is None and declared_role is None and override.lens is None:
            msg = (
                f"unknown agent key {agent_key!r}: set role: or lens: "
                "so it does not silently replace a default role binding"
            )
            raise RegistryValidationError(msg)
        base_role = declared_role or key_role or AgentRole.reviewer
        base = bindings.get(base_role.value) or _build_default_binding(settings, base_role)
        bindings[agent_key] = _apply_override(
            base, override, agent_key=agent_key, settings=settings
        )

    return Registry(bindings)


def resolve_agent_model(
    binding: AgentBinding,
    *,
    settings: RepoSettings,
    slug_runnable: Callable[[str], bool] | None = None,
) -> ResolvedAgentModel:
    """Resolve the runnable model for ``binding``, recording the executed slug (D4)."""
    chain = list(binding.model_chain) or effective_model_chain(settings)
    requested = chain[0]
    executed: str | None = None

    if slug_runnable is not None:
        for slug in chain:
            if slug_runnable(slug):
                executed = slug
                break
    else:
        executed = pick_runnable_slug_from_chain(
            chain,
            allow_fallback=settings.allow_fallback,
        )

    if executed is None:
        msg = f"no runnable model in chain for agent {binding.agent_id!r}"
        raise RuntimeError(msg)

    return ResolvedAgentModel(
        requested_model=requested,
        executed_model=executed,
        recorded_model=executed,
        dispatched_model=executed,
    )


def effective_agent_limits(binding: AgentBinding, *, settings: RepoSettings) -> AgentLimits:
    del settings
    return AgentLimits(budget=binding.budget, timeout_s=binding.timeout_s)
