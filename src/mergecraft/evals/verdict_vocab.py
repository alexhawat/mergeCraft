"""Shared verdict vocabulary for eval bank and packet metadata."""

from __future__ import annotations

from typing import Final

from mergecraft.evidence.gate_policy import GATE_ACTIONS

# GitHub check-run conclusions from ``decide_approval()`` / completion mapping.
CHECK_CONCLUSIONS: Final[frozenset[str]] = frozenset({"success", "failure", "neutral", "timed_out"})

# Evals also record an unavailable result when a gate could not be evaluated.
EXPECTED_VERDICT_VALUES: Final[frozenset[str]] = CHECK_CONCLUSIONS | GATE_ACTIONS | {"unavailable"}

__all__ = ["CHECK_CONCLUSIONS", "EXPECTED_VERDICT_VALUES"]
