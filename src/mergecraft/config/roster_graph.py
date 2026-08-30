"""Canonical ``after:`` graph validation and dispatch-level computation (D15)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


class RosterGraphError(ValueError):
    """Raised when ``after:`` edges are invalid."""


@dataclass(frozen=True, slots=True)
class AfterEdge:
    """One roster binding's ``after:`` dependency."""

    name: str
    after: str | None


def validate_after_graph(nodes: Sequence[AfterEdge]) -> None:
    """Fail closed on unknown dependencies and cycles in ``after:`` edges."""
    by_name = {node.name: node for node in nodes}
    for node in nodes:
        if node.after is None:
            continue
        if node.after == node.name:
            cycle = f"{node.name} -> {node.after}"
            msg = f"after: cycle detected: {cycle}"
            raise RosterGraphError(msg)
        if node.after not in by_name:
            msg = f"after: unknown agent {node.after!r} on {node.name!r}"
            raise RosterGraphError(msg)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str, path: list[str]) -> None:
        if name in visiting:
            start = path.index(name)
            cycle_path = [*path[start:], name]
            cycle = " -> ".join(cycle_path)
            msg = f"after: cycle detected: {cycle}"
            raise RosterGraphError(msg)
        if name in visited:
            return
        node = by_name.get(name)
        if node is None or node.after is None:
            visited.add(name)
            return
        visiting.add(name)
        visit(node.after, [*path, name])
        visiting.remove(name)
        visited.add(name)

    for node in nodes:
        visit(node.name, [])


def dispatch_levels(nodes: Sequence[AfterEdge]) -> dict[str, int]:
    """Return a dense dispatch level index for every node (0 = no ``after:``)."""
    validate_after_graph(nodes)
    by_name = {node.name: node for node in nodes}
    levels: dict[str, int] = {}

    def level_for(name: str) -> int:
        cached = levels.get(name)
        if cached is not None:
            return cached
        node = by_name.get(name)
        if node is None:
            msg = f"after: unknown agent {name!r}"
            raise RosterGraphError(msg)
        if node.after is None:
            levels[name] = 0
            return 0
        result = level_for(node.after) + 1
        levels[name] = result
        return result

    for node in nodes:
        level_for(node.name)
    return levels


def ordered_level_groups(
    nodes: Sequence[AfterEdge],
    *,
    names_in_order: Sequence[str],
) -> tuple[tuple[str, ...], ...]:
    """Group *names_in_order* into dispatch levels derived from *nodes*."""
    if not names_in_order:
        return ()
    levels = dispatch_levels(nodes)
    max_level = max(levels[name] for name in names_in_order)
    grouped: list[tuple[str, ...]] = []
    for level_index in range(max_level + 1):
        batch = tuple(name for name in names_in_order if levels[name] == level_index)
        if batch:
            grouped.append(batch)
    return tuple(grouped)


__all__ = [
    "AfterEdge",
    "RosterGraphError",
    "dispatch_levels",
    "ordered_level_groups",
    "validate_after_graph",
]
