"""Failure truncation with explicit overflow reporting (K2.4 / K5)."""

from __future__ import annotations

from typing import TypeVar

DEFAULT_TRUNCATION_CAP = 3

T = TypeVar("T")


def apply_truncation(items: list[T], *, cap: int = DEFAULT_TRUNCATION_CAP) -> tuple[list[T], int]:
    """Return the analyzed prefix and how many items were dropped."""
    if cap < 0:
        cap = 0
    analyzed = items[:cap]
    overflow = max(len(items) - cap, 0)
    return analyzed, overflow


def truncation_notice(*, overflow: int) -> str | None:
    """Human-readable overflow statement; ``None`` when nothing was dropped."""
    if overflow <= 0:
        return None
    noun = "failure" if overflow == 1 else "failures"
    return f"{overflow} more {noun} not analyzed"


__all__ = ["DEFAULT_TRUNCATION_CAP", "apply_truncation", "truncation_notice"]
