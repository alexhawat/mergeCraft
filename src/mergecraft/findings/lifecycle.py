"""Finding lifecycle states beyond thread resolution (DG2, G7).

Records disputed and waived findings with explicit reasons, and maps review
threads to canonical lifecycle states without altering ``findings/threads.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast, get_args

LifecycleState = Literal[
    "open",
    "resolved-by-change",
    "stale",
    "disputed",
    "waived",
    "deferred",
    "unpublished",
    "withdrawn",
]

_LEDGER_STATES: frozenset[str] = frozenset(get_args(LifecycleState))


def validate_lifecycle_state(raw_state: str) -> LifecycleState:
    """Validate a ledger marker state string against the lifecycle vocabulary."""
    if raw_state not in _LEDGER_STATES:
        msg = f"unknown lifecycle state {raw_state!r}"
        raise ValueError(msg)
    return cast(  # _LEDGER_STATES membership narrows str to LifecycleState
        "LifecycleState",
        raw_state,
    )


@dataclass(frozen=True, slots=True)
class LifecycleRecord:
    """A persisted lifecycle transition for a finding fingerprint."""

    fingerprint: str
    state: LifecycleState
    reason: str | None = None
    expires_at: str | None = None
    round_index: int | None = None
    recorded_at: str | None = None
    source: str | None = None


def dispute_finding(
    fingerprint: str,
    *,
    reason: str,
) -> LifecycleRecord:
    """Record that a finding was challenged by the author or reviewer."""
    return LifecycleRecord(fingerprint=fingerprint, state="disputed", reason=reason)


def waive_finding(
    fingerprint: str,
    *,
    reason: str,
    expires_at: str,
) -> LifecycleRecord:
    """Record an explicit waiver with reason and expiry — not silent suppression."""
    return LifecycleRecord(
        fingerprint=fingerprint,
        state="waived",
        reason=reason,
        expires_at=expires_at,
    )


def lifecycle_state(record: LifecycleRecord) -> LifecycleState:
    """Return the canonical lifecycle state for a record."""
    return record.state


def lifecycle_state_from_thread(thread: dict[str, Any]) -> LifecycleState:
    """Map a normalized review thread to a lifecycle state.

    Stale anchors (outdated but unresolved) are distinguishable from findings
    resolved by the change (outdated and resolved).
    """
    if thread.get("isResolved"):
        return "resolved-by-change"
    if thread.get("isOutdated"):
        return "stale"
    return "open"


__all__ = [
    "LifecycleRecord",
    "LifecycleState",
    "dispute_finding",
    "lifecycle_state",
    "lifecycle_state_from_thread",
    "validate_lifecycle_state",
    "waive_finding",
]
