"""Agent registry — model, prompt, toolset and budget per role and lens (AP1).

Loads bundled defaults plus ``.mergecraft/config.yaml`` overrides. Per-agent
model chains reuse :func:`mergecraft.utils.agent_resolve.effective_model_chain`
and :func:`pick_runnable_slug_from_chain` (D3).
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict

from mergecraft.agents.lens_triggers import LensTriggers
from mergecraft.agents.recall import RECALL_SYSTEM_PROMPT
from mergecraft.agents.reviewer import REVIEWER_SYSTEM_PROMPT
from mergecraft.agents.structured_handoff import agent_finding_output_schema_id
from mergecraft.agents.verifier import VERIFIER_SYSTEM_PROMPT, pinned_judge_model
from mergecraft.config.roster_graph import (
    AfterEdge,
    RosterGraphError,
    ordered_level_groups,
    validate_after_graph,
)
from mergecraft.config.settings import (  # noqa: TC001
    AgentBindingOverride,
    DispatchMode,
)
from mergecraft.mcp.server import build_orchestrator_tools
from mergecraft.mcp.shared import (
    PRIMARY_MUTATING_ALLOWLIST,
    PRIMARY_REVIEWER_ALLOWED_TOOL_CLASSES,
    READONLY_MUTATING_ALLOWLIST,
    REVIEWER_ALLOWED_TOOL_CLASSES,
    VERIFIER_ALLOWED_TOOL_CLASSES,
    ToolClass,
    admits_readonly_role,
)
from mergecraft.models import AUTO_EFFICIENT, MODEL_ALIASES, resolve_display_alias
from mergecraft.types import RECALL_AGENT_NAME, REVIEWER_AGENT_NAME, VERIFIER_AGENT_NAME
from mergecraft.utils.agent_resolve import effective_model_chain, pick_runnable_slug_from_chain

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mergecraft.config.settings import RepoSettings
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.tool_state import ToolState

_DEFAULT_BUDGET: Final[int] = 8
_DEFAULT_TIMEOUT_S: Final[int] = 600
_DEFAULT_PROMPT_VERSION: Final[str] = "1.0.0"


def _lens_prompt_catalog() -> dict[str, tuple[str, str]]:
    from mergecraft.agents.lenses._definitions import LENS_DEFINITIONS

    return {
        f"mergecraft.lens.{lens_id}": (lens.rubric, _DEFAULT_PROMPT_VERSION)
        for lens_id, lens in LENS_DEFINITIONS.items()
    }


_PROMPT_CATALOG: Final[dict[str, tuple[str, str]]] = {
    "mergecraft.reviewer": (REVIEWER_SYSTEM_PROMPT, _DEFAULT_PROMPT_VERSION),
    "mergecraft.verifier": (VERIFIER_SYSTEM_PROMPT, _DEFAULT_PROMPT_VERSION),
    "mergecraft.recall": (RECALL_SYSTEM_PROMPT, _DEFAULT_PROMPT_VERSION),
    "mergecraft.orchestrator": ("", _DEFAULT_PROMPT_VERSION),
    "mergecraft.judge": (VERIFIER_SYSTEM_PROMPT, _DEFAULT_PROMPT_VERSION),
    "mergecraft.classifier": ("", _DEFAULT_PROMPT_VERSION),
    **_lens_prompt_catalog(),
}

_ORCHESTRATOR_TOOL_CLASSES: Final[frozenset[ToolClass]] = frozenset(ToolClass)


class AgentRole(StrEnum):
    orchestrator = "orchestrator"
    reviewer = "reviewer"
    verifier = "verifier"
    recall = "recall"
    judge = "judge"
    classifier = "classifier"


def _mutating_allowlist_for(role: AgentRole) -> frozenset[str]:
    """Return the mutating-tool allowlist for *role*.

    The reviewer uses ``PRIMARY_MUTATING_ALLOWLIST`` (D9 dual allowlist);
    all other roles use the narrower ``READONLY_MUTATING_ALLOWLIST``.
    """
    if role is AgentRole.reviewer:
        return PRIMARY_MUTATING_ALLOWLIST
    return READONLY_MUTATING_ALLOWLIST


class RegistryValidationError(ValueError):
    """Raised when a registry binding fails structural validation."""


class AgentBinding(BaseModel):
    """Frozen resolved identity for one agent role or lens."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str
    role: AgentRole
    lens: str | None = None
    after: str | None = None
    model_chain: tuple[str, ...]
    prompt_id: str
    prompt_version: str
    tool_classes: frozenset[ToolClass]
    budget: int
    timeout_s: int
    dispatch: DispatchMode = "single"
    output_schema: str | None = None
    triggers: LensTriggers | None = None


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


def _default_model_chain(
    settings: RepoSettings,
    *,
    role: AgentRole,
    model_head: str | None = None,
) -> list[str]:
    run_chain = effective_model_chain(settings, head=model_head or None)
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
            return PRIMARY_REVIEWER_ALLOWED_TOOL_CLASSES
        case AgentRole.recall:
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
        case AgentRole.recall:
            return RECALL_AGENT_NAME
        case AgentRole.orchestrator:
            return "mergecraft-orchestrator"
        case AgentRole.judge:
            return "mergecraft-judge"
        case AgentRole.classifier:
            return "mergecraft-classifier"


def _default_prompt_id(role: AgentRole) -> str:
    return f"mergecraft.{role.value}"


def _default_output_schema(role: AgentRole) -> str | None:
    if role in (AgentRole.reviewer, AgentRole.recall):
        return agent_finding_output_schema_id()
    return None


def _build_default_binding(
    settings: RepoSettings,
    role: AgentRole,
    *,
    model_head: str | None = None,
) -> AgentBinding:
    return AgentBinding(
        agent_id=_default_agent_id(role),
        role=role,
        lens=None,
        model_chain=tuple(_default_model_chain(settings, role=role, model_head=model_head)),
        prompt_id=_default_prompt_id(role),
        prompt_version=_DEFAULT_PROMPT_VERSION,
        tool_classes=_default_tool_classes(role),
        budget=_DEFAULT_BUDGET,
        timeout_s=_DEFAULT_TIMEOUT_S,
        output_schema=_default_output_schema(role),
    )


def _resolve_triggers(override: AgentBindingOverride | None) -> LensTriggers | None:
    if override is None or override.triggers is None:
        return None
    return LensTriggers(
        categories=tuple(override.triggers.categories),
        min_risk_band=override.triggers.min_risk_band,
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
        after=override.after if override.after is not None else base.after,
        model_chain=model_chain,
        prompt_id=override.prompt_id or base.prompt_id,
        prompt_version=override.prompt_version or base.prompt_version,
        tool_classes=base.tool_classes,
        budget=override.budget if override.budget is not None else base.budget,
        timeout_s=override.timeout_s if override.timeout_s is not None else base.timeout_s,
        dispatch=override.dispatch or base.dispatch,
        output_schema=base.output_schema,
        triggers=_resolve_triggers(override) if override.triggers is not None else base.triggers,
    )


class Registry:
    """Resolved agent roster for one repo configuration.

    Multiple lens-less bindings may share a role (for example two ``reviewer``
    entries). :meth:`resolve_role` returns the binding whose config key equals
    the role name when present, otherwise the first binding in stable order.
    :meth:`resolve_roles` returns every binding for a role in that same order:
    the role-named key first, then every other key in config declaration order
    (not alphabetical — ``reviewer10`` does not sort before ``reviewer2``).
    :meth:`resolve_role_levels` groups those bindings into dispatch levels from
    each binding's ``after:`` dependency (D15).
    """

    def __init__(
        self,
        bindings: dict[str, AgentBinding],
        *,
        configured_keys: frozenset[str] = frozenset(),
    ) -> None:
        self._bindings = bindings
        self._configured_keys = configured_keys
        self._by_role: dict[AgentRole, list[tuple[str, AgentBinding]]] = {}
        for key, binding in bindings.items():
            if binding.lens is None:
                self._by_role.setdefault(binding.role, []).append((key, binding))

    def _primary_role_entries(
        self,
        role: AgentRole,
        entries: list[tuple[str, AgentBinding]],
    ) -> list[tuple[str, AgentBinding]]:
        role_key = role.value
        role_named = [entry for entry in entries if entry[0] == role_key]
        if role_key in self._configured_keys:
            return role_named
        configured_custom = [entry for entry in entries if entry[0] in self._configured_keys]
        if configured_custom:
            return configured_custom[:1]
        return role_named

    def _ordered_role_entries(self, role: AgentRole) -> list[tuple[str, AgentBinding]]:
        entries = self._by_role.get(role, [])
        if not entries:
            return []
        primary = self._primary_role_entries(role, entries)
        primary_keys = {key for key, _ in primary}
        others = [entry for entry in entries if entry[0] not in primary_keys]
        return primary + others

    def _ordered_role_bindings(self, role: AgentRole) -> tuple[AgentBinding, ...]:
        return tuple(binding for _, binding in self._ordered_role_entries(role))

    def resolve_role(self, role: AgentRole | str) -> AgentBinding:
        key = AgentRole(role) if isinstance(role, str) else role
        ordered = self._ordered_role_bindings(key)
        if not ordered:
            msg = f"no binding for role {key!r}"
            raise KeyError(msg)
        return ordered[0]

    def resolve_roles(self, role: AgentRole | str) -> tuple[AgentBinding, ...]:
        key = AgentRole(role) if isinstance(role, str) else role
        return self._ordered_role_bindings(key)

    def resolve_role_levels(self, role: AgentRole | str) -> tuple[tuple[AgentBinding, ...], ...]:
        """Return dispatch levels for *role* derived from ``after:`` edges (D15)."""
        key = AgentRole(role) if isinstance(role, str) else role
        entries = self._ordered_role_entries(key)
        if not entries:
            return ()
        nodes = tuple(
            AfterEdge(name=agent_key, after=binding.after) for agent_key, binding in entries
        )
        ordered_keys = tuple(agent_key for agent_key, _binding in entries)
        level_groups = ordered_level_groups(nodes, names_in_order=ordered_keys)
        by_key = {agent_key: binding for agent_key, binding in entries}
        return tuple(tuple(by_key[agent_key] for agent_key in group) for group in level_groups)

    def resolve_agent_ref(self, ref: str) -> AgentBinding:
        """Resolve a pipeline agent reference (role name or custom agent id)."""
        try:
            role = AgentRole(ref)
        except ValueError:
            role = None
        if role is not None:
            try:
                return self.resolve_role(role)
            except KeyError:
                pass
        if ref in self._bindings:
            return self._bindings[ref]
        msg = f"no binding for agent ref {ref!r}"
        raise KeyError(msg)

    def resolve_tool_names(self, binding: AgentBinding, ctx: ToolContext) -> list[str]:
        tools = build_orchestrator_tools(ctx)
        if binding.role is AgentRole.orchestrator:
            return [spec.name for spec in tools]
        return [
            spec.name
            for spec in tools
            if admits_readonly_role(
                spec,
                binding.tool_classes,
                mutating_allowlist=_mutating_allowlist_for(binding.role),
            )
        ]

    def all_bindings(self) -> tuple[AgentBinding, ...]:
        return tuple(self._bindings.values())

    def iter_lens_bindings(self) -> tuple[AgentBinding, ...]:
        """Yield lens-scoped reviewer bindings in stable order."""
        return tuple(
            binding
            for binding in sorted(self._bindings.values(), key=lambda item: item.agent_id)
            if binding.lens is not None
        )

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
            if binding.lens is not None and binding.triggers is None:
                msg = (
                    f"unreachable lens {binding.lens!r} on agent {binding.agent_id!r} "
                    "(lens missing trigger metadata)"
                )
                raise RegistryValidationError(msg)
            if binding.role is not AgentRole.orchestrator:
                terminal = "submit_review_verdict"
                if terminal in binding.tool_classes:
                    msg = f"read-only agent {binding.agent_id!r} holds terminal-protocol tool"
                    raise RegistryValidationError(msg)


def resolve_agent_ref(registry: Registry, ref: str) -> AgentBinding:
    """Resolve a pipeline step agent reference against a registry."""
    return registry.resolve_agent_ref(ref)


def load_registry(
    *,
    settings: RepoSettings,
    repo_root: Path | None = None,
    model_head: str | None = None,
) -> Registry:
    """Load defaults merged with ``settings.agents`` overrides.

    ``model_head`` is the model the operator named for this run (the CLI
    ``--model`` flag, or the Action ``with: model:`` input). It becomes the
    head of every default binding's chain so an explicit request outranks
    ``MERGECRAFT_MODEL`` and ``.mergecraft/config.yaml`` for subagents too
    (issue #468). Per-agent ``model_chain`` overrides still win.
    """
    del repo_root  # reserved for future repo-local agent manifests
    bindings: dict[str, AgentBinding] = {}
    for role in AgentRole:
        bindings[role.value] = _build_default_binding(settings, role, model_head=model_head)

    bindings.update(
        __import__(
            "mergecraft.agents.lenses._bindings",
            fromlist=["bundled_lens_bindings"],
        ).bundled_lens_bindings(settings=settings)
    )
    lens_keys: dict[str, str] = {
        binding.lens: key for key, binding in bindings.items() if binding.lens is not None
    }

    for agent_key, override in settings.agents.items():
        key_role = _parse_role(agent_key)
        declared_role = _parse_role(override.role) if override.role is not None else None
        if key_role is None and declared_role is None and override.lens is None:
            msg = (
                f"unknown agent key {agent_key!r}: set role: or lens: "
                "so it does not silently replace a default role binding"
            )
            raise RegistryValidationError(msg)
        if override.lens is not None and override.lens in lens_keys:
            base = bindings[lens_keys[override.lens]]
        else:
            base_role = declared_role or key_role or AgentRole.reviewer
            base = bindings.get(base_role.value) or _build_default_binding(
                settings, base_role, model_head=model_head
            )
        merged = _apply_override(base, override, agent_key=agent_key, settings=settings)
        if merged.lens is not None and merged.lens in lens_keys:
            stale_key = lens_keys[merged.lens]
            if stale_key != agent_key:
                bindings.pop(stale_key, None)
        if merged.lens is not None:
            lens_keys[merged.lens] = agent_key
        bindings[agent_key] = merged

    orchestrator_keys = [
        key
        for key, binding in bindings.items()
        if binding.role is AgentRole.orchestrator and binding.lens is None
    ]
    if len(orchestrator_keys) > 1:
        joined = ", ".join(orchestrator_keys)
        msg = f"cannot load multiple orchestrator bindings (D7): {joined}"
        raise RegistryValidationError(msg)

    after_nodes = tuple(
        AfterEdge(name=agent_key, after=binding.after)
        for agent_key, binding in bindings.items()
        if binding.after is not None
    )
    if after_nodes:
        all_nodes = tuple(
            AfterEdge(name=agent_key, after=binding.after)
            for agent_key, binding in bindings.items()
        )
        try:
            validate_after_graph(all_nodes)
        except RosterGraphError as exc:
            raise RegistryValidationError(str(exc)) from exc

    return Registry(bindings, configured_keys=frozenset(settings.agents.keys()))


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


def effective_agent_limits(
    binding: AgentBinding,
    *,
    settings: RepoSettings,
    round_index: int = 1,
) -> AgentLimits:
    from mergecraft.utils.run_bounds import round_budget_multiplier

    multiplier = round_budget_multiplier(
        settings.review.round_budgets,
        round_index=round_index,
    )
    scaled_budget = int(binding.budget * multiplier)
    return AgentLimits(budget=scaled_budget, timeout_s=binding.timeout_s)


def subagent_limits_for_round(
    binding: AgentBinding,
    *,
    settings: RepoSettings,
    tool_state: ToolState,
) -> AgentLimits:
    """Resolve round-aware subagent limits for production dispatch."""
    from mergecraft.findings.ledger import ledger_round_index

    return effective_agent_limits(
        binding,
        settings=settings,
        round_index=ledger_round_index(tool_state),
    )
