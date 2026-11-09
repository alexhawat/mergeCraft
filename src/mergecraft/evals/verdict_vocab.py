"""Shared verdict vocabulary for eval bank and packet metadata."""

from __future__ import annotations

from typing import Final

# GitHub check-run conclusions from ``decide_approval()`` / completion mapping.
CHECK_CONCLUSIONS: Final[frozenset[str]] = frozenset({"success", "failure", "neutral", "timed_out"})

# W9 thermostat gate actions — not check conclusions.
GATE_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "auto_merge",
        "block",
        "request_changes",
        "require_human_review",
        "require_more_tests",
        "quarantine",
        "escalate",
        "unavailable",
    }
)

EXPECTED_VERDICT_VALUES: Final[frozenset[str]] = CHECK_CONCLUSIONS | GATE_ACTIONS

__all__ = [
    "CHECK_CONCLUSIONS",
    "EXPECTED_VERDICT_VALUES",
    "GATE_ACTIONS",
]
