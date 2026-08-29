"""Shared finding severity ordering for merge and verdict paths."""

from __future__ import annotations

SEVERITY_ORDER: dict[str, int] = {
    "Trivial": 0,
    "Minor": 1,
    "Major": 2,
    "Critical": 3,
}


def severity_rank(value: str) -> int:
    """Return a numeric rank for *value*; unknown severities sort below Minor."""
    return SEVERITY_ORDER.get(value, 0)


__all__ = ["SEVERITY_ORDER", "severity_rank"]
