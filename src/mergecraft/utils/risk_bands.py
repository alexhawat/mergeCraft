"""Shared review risk-band ordering (pipeline predicates and model routing)."""

from __future__ import annotations

from typing import Final

RISK_BANDS: Final[frozenset[str]] = frozenset({"low", "medium", "high", "critical"})
_RISK_ORDER: Final[dict[str, int]] = {"low": 0, "medium": 1, "high": 2, "critical": 3}


# Unknown is never green (#1056): a band outside the order ranks above every
# known band, so it can only meet a threshold, never slip under one.
_UNKNOWN_RISK_RANK: Final[int] = max(_RISK_ORDER.values()) + 1


def risk_at_or_above(risk: str, threshold: str) -> bool:
    """Return whether ``risk`` is at or above ``threshold`` in the shared band order.

    An unrecognised ``risk`` ranks highest, so it is at or above every
    threshold. An unrecognised ``threshold`` still ranks lowest, so the
    predicate holds for any risk (the escalating direction for both).
    """
    actual = str(risk).casefold()
    return _RISK_ORDER.get(actual, _UNKNOWN_RISK_RANK) >= _RISK_ORDER.get(
        str(threshold).casefold(), 0
    )


__all__ = ["RISK_BANDS", "risk_at_or_above"]
