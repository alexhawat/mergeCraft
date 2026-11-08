"""Allowed finding lifecycle transitions enforced at ``FindingLedger.record`` (#SM2)."""

from __future__ import annotations

from typing import Final

from mergecraft.findings.lifecycle import LifecycleState

# First record for a fingerprint may enter any state; thereafter only listed edges.
_ALLOWED_LIFECYCLE_TRANSITIONS: Final[dict[LifecycleState, frozenset[LifecycleState]]] = {
    "open": frozenset(
        {
            "open",
            "resolved-by-change",
            "stale",
            "disputed",
            "waived",
            "deferred",
            "unpublished",
            "withdrawn",
        }
    ),
    "deferred": frozenset({"open", "deferred", "unpublished", "withdrawn"}),
    "unpublished": frozenset({"open", "unpublished", "withdrawn"}),
    "withdrawn": frozenset({"withdrawn"}),
    "resolved-by-change": frozenset({"resolved-by-change", "stale", "open"}),
    "stale": frozenset({"stale", "open", "resolved-by-change", "disputed"}),
    "disputed": frozenset({"disputed", "open", "waived", "withdrawn"}),
    "waived": frozenset({"waived", "open", "disputed"}),
}


def lifecycle_transition_allowed(
    prior: LifecycleState | None,
    new: LifecycleState,
) -> bool:
    """Return whether ``new`` is legal after ``prior`` (``None`` = first record)."""
    if prior is None:
        return True
    allowed = _ALLOWED_LIFECYCLE_TRANSITIONS.get(prior, frozenset({prior}))
    return new in allowed


def assert_lifecycle_transition(prior: LifecycleState | None, new: LifecycleState) -> None:
    """Raise ``ValueError`` when ``new`` is not an allowed successor of ``prior``."""
    if not lifecycle_transition_allowed(prior, new):
        msg = f"illegal lifecycle transition {prior!r} -> {new!r}"
        raise ValueError(msg)


__all__ = [
    "_ALLOWED_LIFECYCLE_TRANSITIONS",
    "assert_lifecycle_transition",
    "lifecycle_transition_allowed",
]
