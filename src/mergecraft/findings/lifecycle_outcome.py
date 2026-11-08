"""Project ledger lifecycle states to advisory human outcomes (#SM2)."""

from __future__ import annotations

from mergecraft.findings.lifecycle import LifecycleState

_LIFECYCLE_TO_ADVISORY: dict[LifecycleState, str] = {
    "resolved-by-change": "fixed",
    "open": "unknown",
    "stale": "unknown",
    "disputed": "rejected",
    "waived": "intentional",
    "deferred": "unknown",
    "unpublished": "unknown",
    "withdrawn": "ignored",
}


def advisory_outcome_for_lifecycle(state: LifecycleState) -> str:
    """Map one ledger state to an advisory outcome (total, no gaps)."""
    return _LIFECYCLE_TO_ADVISORY[state]


def all_lifecycle_states_mapped() -> frozenset[LifecycleState]:
    """Every ``LifecycleState`` value has an advisory projection."""
    from typing import get_args

    return frozenset(get_args(LifecycleState))


__all__ = ["advisory_outcome_for_lifecycle", "all_lifecycle_states_mapped"]
