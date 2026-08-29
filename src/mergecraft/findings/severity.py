"""Shared finding severity ordering for merge and verdict paths."""

from __future__ import annotations

from mergecraft.agents.gates import BLOCKING_SEVERITIES

SEVERITY_ORDER: dict[str, int] = {
    "Trivial": 0,
    "Minor": 1,
    "Major": 2,
    "Critical": 3,
}

_SEVERITY_ALIASES: dict[str, str] = {
    "critical": "Critical",
    "major": "Major",
    "minor": "Minor",
    "trivial": "Trivial",
    "warning": "Minor",
    "error": "Major",
}


def normalize_severity(value: object) -> str:
    """Map raw severity text to the canonical review taxonomy label."""
    text = str(value or "Minor").strip()
    lowered = text.casefold()
    if lowered in _SEVERITY_ALIASES:
        return _SEVERITY_ALIASES[lowered]
    if text in BLOCKING_SEVERITIES or text in {"Minor", "Trivial"}:
        return text
    return "Minor"


def severity_rank(value: str) -> int:
    """Return a numeric rank for *value*; unknown severities sort below Minor."""
    return SEVERITY_ORDER.get(value, 0)


def normalized_severity_rank(value: object) -> int:
    """Normalize *value* then return its severity rank."""
    return severity_rank(normalize_severity(value))


__all__ = [
    "SEVERITY_ORDER",
    "normalize_severity",
    "normalized_severity_rank",
    "severity_rank",
]
