"""Failure cleanup for timeout, cancel, and crash modes (#365).

Process-group kill lives in ``utils/process_group``.

Exports:
    RecoveryOutcome: Named cleanup result.
    cleanup_on_failure: Cleanup for timeout, cancel, and crash modes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from loguru import logger

from mergecraft.utils.process_group import kill_all_active_process_groups

CLEANUP_FAILURE_MODES: Final[frozenset[str]] = frozenset(
    {
        "timeout",
        "cancellation",
        "provider_crash",
        "analyzer_crash",
        "parent_process_termination",
    }
)


@dataclass(frozen=True, slots=True)
class RecoveryOutcome:
    """Cleanup result."""

    status: str | None = None
    cleaned: bool | None = None


def cleanup_on_failure(mode: str) -> RecoveryOutcome:
    """Run cleanup for timeout, cancellation, and crash modes.

    Args:
        mode: One of the named cleanup failure modes.

    Returns:
        Outcome with ``cleaned`` true when the mode is recognised.
    """
    if mode not in CLEANUP_FAILURE_MODES:
        raise ValueError(f"unknown cleanup failure mode: {mode}")
    logger.debug("Cleanup after failure mode {}", mode)
    kill_all_active_process_groups()
    return RecoveryOutcome(cleaned=True, status="degraded")
