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

from mergecraft.config.settings_snapshot import (
    RepoSettingsSnapshot,
    assert_config_unchanged,
    capture_repo_settings_snapshot,
    config_yaml_hash,
)

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


def _validate_after_graph(entries: tuple[RosterEntry, ...]) -> None:
    by_name = {entry.name: entry for entry in entries}
    for entry in entries:
        if entry.after is None:
            continue
        if entry.after == entry.name:
            cycle = f"{entry.name} -> {entry.after}"
            msg = f"after: cycle detected: {cycle}"
            raise AgentRosterError(msg)
        if entry.after not in by_name:
            msg = f"after: unknown agent {entry.after!r} on {entry.name!r}"
            raise AgentRosterError(msg)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str, path: list[str]) -> None:
        if name in visiting:
            start = path.index(name)
            cycle_path = [*path[start:], name]
            cycle = " -> ".join(cycle_path)
            msg = f"after: cycle detected: {cycle}"
            raise AgentRosterError(msg)
        if name in visited:
            return
        entry = by_name.get(name)
        if entry is None or entry.after is None:
            visited.add(name)
            return
        visiting.add(name)
        visit(entry.after, [*path, name])
        visiting.remove(name)
        visited.add(name)

    for entry in entries:
        visit(entry.name, [])


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
    _validate_after_graph(roster.entries)
    return roster


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
    "RepoSettingsSnapshot",
    "Roster",
    "RosterEntry",
    "add_model",
    "assert_config_unchanged",
    "assign_slot",
    "capture_repo_settings_snapshot",
    "config_yaml_hash",
    "load_roster",
    "parse_slot",
    "remove_slot",
    "write_roster",
]
