"""Scan roster model chains against a workflow auth manifest (D1a)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.config.agent_roster import AgentRosterError, Roster, load_roster
from mergecraft.models import parse_model

if TYPE_CHECKING:
    from collections.abc import Mapping


def iter_roster_model_slots(roster: Roster) -> tuple[tuple[str, str, str], ...]:
    """Yield ``(agent_name, slot, slug)`` for every configured model chain entry."""
    slots: list[tuple[str, str, str]] = []
    for entry in roster.entries:
        for index, slug in enumerate(entry.model_chain):
            slots.append((entry.name, f"p{index}", slug))
    return tuple(slots)


def collect_unwired_roster_models(
    *,
    roster: Roster,
    wired_providers: frozenset[str],
) -> list[tuple[str, str, str, str]]:
    """Return ``(agent, slot, slug, provider)`` rows absent from *wired_providers*."""
    unwired: list[tuple[str, str, str, str]] = []
    for agent_name, slot, slug in iter_roster_model_slots(roster):
        try:
            provider, _model_id = parse_model(slug)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        provider_key = provider.lower()
        if provider_key not in wired_providers:
            unwired.append((agent_name, slot, slug, provider_key))
    return unwired


def reviewer_p0_slug(raw: Mapping[str, object]) -> str | None:
    """Return the first reviewer model slug from a config mapping, if any."""
    roster = load_roster(raw)
    for entry in roster.entries:
        if (entry.name == "reviewer" or entry.role == "reviewer") and entry.model_chain:
            return entry.model_chain[0]
    for entry in roster.entries:
        if entry.model_chain:
            return entry.model_chain[0]
    return None


def reviewer_p0_slug_from_config(raw: Mapping[str, object]) -> str | None:
    """Return reviewer p0 slug or raise when roster parsing fails."""
    try:
        return reviewer_p0_slug(raw)
    except AgentRosterError as exc:
        raise ValueError(str(exc)) from exc


__all__ = [
    "collect_unwired_roster_models",
    "iter_roster_model_slots",
    "reviewer_p0_slug",
    "reviewer_p0_slug_from_config",
]
