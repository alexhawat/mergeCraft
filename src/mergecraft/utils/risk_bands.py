"""Shared review risk-band ordering (pipeline predicates and model routing)."""

from __future__ import annotations

from typing import Final

RISK_BANDS: Final[frozenset[str]] = frozenset({"low", "medium", "high", "critical"})
_RISK_ORDER: Final[dict[str, int]] = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def risk_at_or_above(risk: str, threshold: str) -> bool:
    """Return whether ``risk`` is at or above ``threshold`` in the shared band order."""
    actual = str(risk).casefold()
    return _RISK_ORDER.get(actual, 0) >= _RISK_ORDER.get(str(threshold).casefold(), 0)


__all__ = ["RISK_BANDS", "risk_at_or_above"]
