"""Failure cleanup for timeout, cancel, and crash modes (#365).

Process-group kill lives in ``utils/process_group``.

Exports:
    cleanup_on_failure: Cleanup for timeout, cancel, and crash modes.
"""

from __future__ import annotations

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


def cleanup_on_failure(mode: str) -> None:
    """Run cleanup for timeout, cancellation, and crash modes.

    Args:
        mode: One of the named cleanup failure modes.

    Raises:
        ValueError: When ``mode`` is not a recognised cleanup failure mode.
    """
    if mode not in CLEANUP_FAILURE_MODES:
        raise ValueError(f"unknown cleanup failure mode: {mode}")
    logger.debug("Cleanup after failure mode {}", mode)
    kill_all_active_process_groups()
