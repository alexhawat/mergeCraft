"""Shared SCM wire types (not GitHub-specific)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NamedTuple


@dataclass(frozen=True, slots=True)
class LinkedIssue:
    """One issue a pull request closes, as its closing references report it.

    Attributes:
        number (int): The issue number.
        author_login (str): Login of the issue's author (``""`` when unknown,
            e.g. a deleted account).
        body (str): The issue body (``""`` when the issue has none).
    """

    number: int
    author_login: str
    body: str


class ListedItems(NamedTuple):
    """One SCM list walk: items plus whether the catalog is complete.

    ``total_count`` is the API's reported total when present (optional).
    """

    items: list[dict[str, Any]]
    incomplete: bool
    total_count: int | None = None


def require_listed(result: object) -> ListedItems:
    """Reject a bare list: that must not look like a complete catalog."""
    if isinstance(result, ListedItems):
        return result
    msg = f"expected ListedItems, got {type(result).__name__}"
    raise TypeError(msg)
