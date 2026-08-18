"""Finding lifecycle states beyond thread resolution (DG2, G7).

Records disputed and waived findings with explicit reasons, and maps review
threads to canonical lifecycle states without altering ``findings/threads.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

LifecycleState = Literal["open", "resolved-by-change", "stale", "disputed", "waived"]


@dataclass(frozen=True, slots=True)
class LifecycleRecord:
    """A persisted lifecycle transition for a finding fingerprint."""

    fingerprint: str
    state: LifecycleState
    reason: str | None = None
    expires_at: str | None = None


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
    "waive_finding",
]
