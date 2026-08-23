"""Shared verdict vocabulary for eval bank and packet metadata."""

from __future__ import annotations

from typing import Final

# Check-run conclusions — what ``decide_approval()`` emits today.
# Lane verdicts — the W9 thermostat action vocabulary (#46, W9.1).
EXPECTED_VERDICT_VALUES: Final[frozenset[str]] = frozenset(
    {
        "success",
        "failure",
        "auto_merge",
        "block",
        "request_changes",
        "require_human_review",
        "require_more_tests",
        "quarantine",
        "escalate",
        "unavailable",
        "neutral",
    }
)

__all__ = ["EXPECTED_VERDICT_VALUES"]
