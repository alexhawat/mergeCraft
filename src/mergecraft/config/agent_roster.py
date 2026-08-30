"""Agent roster slot primitives and config read/write (wave plan 11).

Trust-boundary reads use :mod:`mergecraft.config.settings_snapshot` (AG2 / D9) —
import those helpers from here or from ``settings_snapshot`` directly; do not
duplicate snapshot logic in this module.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

from mergecraft.config.roster_graph import AfterEdge, RosterGraphError, validate_after_graph
from mergecraft.models import PROVIDERS

_SLOT_RE = re.compile(r"^p(\d+)$")

_AGENTS_KEY = "agents"
_MODEL_CHAIN_KEY = "modelChain"
_AFTER_KEY = "after"
_ROLE_KEY = "role"


class AgentRosterError(ValueError):
    """Raised when roster config or slot operations are invalid."""


def parse_slot(token: str) -> int:
    """Parse a positional slot alias such as ``p0`` into a zero-based index."""
    match = _SLOT_RE.match(token)
    if match is None:
        msg = f"invalid slot {token!r}; expected pN (e.g. p0)"
        raise AgentRosterError(msg)
    return int(match.group(1))


def _next_assignable_slot(chain_len: int) -> str:
    return f"p{chain_len}"


def assign_slot(chain: list[str], index: int, slug: str) -> tuple[list[str], str]:
    """Replace *slug* at *index*, or append when *index* is the next dense slot."""
    if index < 0:
        msg = f"invalid slot index {index}; expected p0 or higher"
        raise AgentRosterError(msg)
    if index < len(chain):
        updated = [*chain]
        updated[index] = slug
        return updated, f"assigned {slug!r} at p{index}"
    if index == len(chain):
        return [*chain, slug], f"assigned {slug!r} at p{index}"
    next_slot = _next_assignable_slot(len(chain))
    msg = (
        f"cannot assign p{index} on a {len(chain)}-long chain; next assignable slot is {next_slot}"
    )
    raise AgentRosterError(msg)


def add_model(chain: list[str], slug: str) -> tuple[list[str], bool]:
    """Append *slug* to *chain*; return ``(chain, True)`` when already present."""
    if slug in chain:
        return chain, True
    return [*chain, slug], False


def remove_slot(chain: list[str], index: int) -> list[str]:
    """Remove the model at *index* and compact; the chain must not become empty."""
    if index < 0 or index >= len(chain):
        msg = f"invalid slot index {index} for chain of length {len(chain)}"
        raise AgentRosterError(msg)
    if len(chain) == 1:
        msg = "modelChain must not become empty"
        raise AgentRosterError(msg)
    return [item for slot, item in enumerate(chain) if slot != index]


@dataclass(frozen=True, slots=True)
class RosterEntry:
    """One agent binding from ``agents:`` in config."""

    name: str
    model_chain: tuple[str, ...]
    role: str | None = None
    after: str | None = None


@dataclass(frozen=True, slots=True)
class Roster:
    """Validated view of the ``agents:`` roster block."""

    entries: tuple[RosterEntry, ...]

    def entry_by_name(self) -> dict[str, RosterEntry]:
        return {entry.name: entry for entry in self.entries}


def model_chain_from_entry(entry: Mapping[str, Any]) -> list[str]:
    """Return ``modelChain`` from one ``agents:`` entry as a mutable list."""
    return list(_model_chain_from_entry(entry))


def _model_chain_from_entry(entry: Mapping[str, Any]) -> tuple[str, ...]:
    chain = entry.get(_MODEL_CHAIN_KEY)
    if chain is None:
        return ()
    if not isinstance(chain, list):
        msg = f"agents entry modelChain must be a list, got {type(chain).__name__}"
        raise AgentRosterError(msg)
    return tuple(str(item) for item in chain)


def _after_from_entry(entry: Mapping[str, Any]) -> str | None:
    if _AFTER_KEY not in entry:
        return None
    value = entry[_AFTER_KEY]
    if value is None:
        return None
    return str(value)


def _effective_roster_role(name: str, role: str | None) -> str:
    if role is not None:
        return role
    from mergecraft.agents.registry import AgentRole

    try:
        return AgentRole(name).value
    except ValueError:
        msg = f"agents.{name} missing role: and name is not a known AgentRole"
        raise AgentRosterError(msg) from None


def _validate_after_same_role(entries: tuple[RosterEntry, ...]) -> None:
    by_name = {entry.name: entry for entry in entries}
    for entry in entries:
        if entry.after is None:
            continue
        target = by_name.get(entry.after)
        if target is None:
            continue
        entry_role = _effective_roster_role(entry.name, entry.role)
        target_role = _effective_roster_role(target.name, target.role)
        if entry_role != target_role:
            msg = (
                f"after: {entry.after!r} on {entry.name!r} must reference an agent "
                f"with the same role ({entry_role!r} != {target_role!r})"
            )
            raise AgentRosterError(msg)


def load_roster(config: Mapping[str, Any]) -> Roster:
    """Load and validate the ``agents:`` roster from a config mapping."""
    agents = config.get(_AGENTS_KEY)
    if agents is None:
        return Roster(entries=())
    if not isinstance(agents, Mapping):
        msg = "agents block must be a mapping"
        raise AgentRosterError(msg)

    entries: list[RosterEntry] = []
    for name, raw_entry in agents.items():
        agent_name = str(name)
        if not isinstance(raw_entry, Mapping):
            msg = f"agents.{agent_name} must be a mapping"
            raise AgentRosterError(msg)
        role_value = raw_entry.get(_ROLE_KEY)
        role = str(role_value).lower() if role_value is not None else None
        entries.append(
            RosterEntry(
                name=agent_name,
                model_chain=_model_chain_from_entry(raw_entry),
                role=role,
                after=_after_from_entry(raw_entry),
            )
        )

    roster = Roster(entries=tuple(entries))
    try:
        validate_after_graph(
            tuple(AfterEdge(name=entry.name, after=entry.after) for entry in roster.entries)
        )
    except RosterGraphError as exc:
        raise AgentRosterError(str(exc)) from exc
    _validate_after_same_role(roster.entries)
    return roster


def preferred_model_slug(provider_label: str) -> str:
    """Return ``provider/model-id`` for the catalog's first ``preferred=True`` model."""
    normalized = provider_label.strip().lower()
    provider = PROVIDERS.get(normalized)
    if provider is None:
        msg = f"unknown provider {provider_label!r}"
        raise AgentRosterError(msg)
    for model_id, model in provider.models.items():
        if model.preferred:
            return f"{normalized}/{model_id}"
    msg = f"provider {provider_label!r} has no preferred model in the catalog"
    raise AgentRosterError(msg)


def reviewer_model_chain_is_empty(config: Mapping[str, Any]) -> bool:
    """Return whether ``agents.reviewer.modelChain`` is absent or empty."""
    agents = config.get(_AGENTS_KEY)
    if not isinstance(agents, Mapping):
        return True
    reviewer = agents.get("reviewer")
    if not isinstance(reviewer, Mapping):
        return True
    chain = reviewer.get(_MODEL_CHAIN_KEY)
    if chain is None:
        return True
    if isinstance(chain, list):
        return len(chain) == 0
    return False


def seed_reviewer_p0_if_empty(
    config: MutableMapping[str, Any],
    provider_label: str,
) -> str | None:
    """Seed ``agents.reviewer`` p0 when the chain is empty; return slug or ``None``."""
    if not reviewer_model_chain_is_empty(config):
        return None
    slug = preferred_model_slug(provider_label)
    agents = config.get(_AGENTS_KEY)
    if not isinstance(agents, MutableMapping):
        agents = {}
        config[_AGENTS_KEY] = agents
    reviewer = agents.get("reviewer")
    if not isinstance(reviewer, MutableMapping):
        reviewer = {}
        agents["reviewer"] = reviewer
    reviewer[_ROLE_KEY] = "reviewer"
    reviewer[_MODEL_CHAIN_KEY] = [slug]
    models = config.get("models")
    if isinstance(models, list):
        if slug not in [str(item) for item in models]:
            models.insert(0, slug)
    else:
        config["models"] = [slug]
    return slug


def write_roster(config: MutableMapping[str, Any], roster: Roster) -> None:
    """Write *roster* into *config*'s ``agents:`` block in place.

    Mutates the existing ``agents`` mapping so caller-owned key order and any
    sibling keys outside ``agents:`` are preserved. Omits ``after:`` when unset
    rather than serialising ``after: null``.
    """
    agents = config.get(_AGENTS_KEY)
    if agents is None:
        agents = {}
        config[_AGENTS_KEY] = agents
    if not isinstance(agents, MutableMapping):
        msg = "agents block must be a mapping"
        raise AgentRosterError(msg)

    roster_by_name = roster.entry_by_name()
    for name, raw_entry in list(agents.items()):
        agent_name = str(name)
        if agent_name not in roster_by_name:
            continue
        if not isinstance(raw_entry, MutableMapping):
            msg = f"agents.{agent_name} must be a mapping"
            raise AgentRosterError(msg)
        entry = roster_by_name[agent_name]
        raw_entry[_MODEL_CHAIN_KEY] = list(entry.model_chain)
        if entry.role is not None:
            raw_entry[_ROLE_KEY] = entry.role
        if entry.after is None:
            raw_entry.pop(_AFTER_KEY, None)
        else:
            raw_entry[_AFTER_KEY] = entry.after


__all__ = [
    "AgentRosterError",
    "Roster",
    "RosterEntry",
    "add_model",
    "assign_slot",
    "load_roster",
    "model_chain_from_entry",
    "parse_slot",
    "preferred_model_slug",
    "remove_slot",
    "reviewer_model_chain_is_empty",
    "seed_reviewer_p0_if_empty",
    "write_roster",
]
