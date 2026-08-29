"""Scan roster model chains against a workflow auth manifest (D1a)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.models import parse_model

if TYPE_CHECKING:
    from mergecraft.config.agent_roster import Roster


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
        except ValueError:
            continue
        provider_key = provider.lower()
        if provider_key not in wired_providers:
            unwired.append((agent_name, slot, slug, provider_key))
    return unwired


__all__ = [
    "collect_unwired_roster_models",
    "iter_roster_model_slots",
]
