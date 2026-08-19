"""Reproducible provenance records for retrieved context items."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContextItem:
    """One retrieved context fragment with reproducible citation metadata."""

    repo: str
    sha: str
    path: str
    reason: str
    text: str
    token_cost: int

    def as_citation(self) -> str:
        """Return ``repo@sha:path`` citation string (convention 4)."""
        return f"{self.repo}@{self.sha}:{self.path}"


@dataclass(frozen=True, slots=True)
class ContextInspectEntry:
    """Per-item token accounting in an inspect report."""

    path: str
    token_cost: int


@dataclass(frozen=True, slots=True)
class ContextInspectReport:
    """Aggregate token cost report for a set of context items."""

    total_tokens: int
    items: tuple[ContextInspectEntry, ...]


def inspect_context(items: list[ContextItem]) -> ContextInspectReport:
    """Summarize per-item and total token costs for budget visibility."""
    entries = tuple(
        ContextInspectEntry(path=item.path, token_cost=item.token_cost) for item in items
    )
    return ContextInspectReport(
        total_tokens=sum(entry.token_cost for entry in entries),
        items=entries,
    )


__all__ = [
    "ContextInspectEntry",
    "ContextInspectReport",
    "ContextItem",
    "inspect_context",
]
