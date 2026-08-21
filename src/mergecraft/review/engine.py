"""Single review engine over one ``ReviewSnapshot`` (#380).

Exports:
    run_from_snapshot: Admit a snapshot into the canonical engine.
"""

from __future__ import annotations

from mergecraft.review.snapshot import (
    CANONICAL_STAGE_NAMES,
    ReviewSnapshot,
)

_ALLOWED_MODES: frozenset[str] = frozenset({"Review", "IncrementalReview"})


def run_from_snapshot(snapshot: ReviewSnapshot) -> ReviewSnapshot:
    """Validate ``snapshot`` and admit it as the shared review engine input.

    CLI, Action, and SCM call this with the same type. Stage names, per-stage
    timeouts, and manifest observability are enforced here so a second
    execution path cannot skip the contract.
    """
    if snapshot.mode not in _ALLOWED_MODES:
        msg = f"unsupported review mode {snapshot.mode!r}"
        raise ValueError(msg)
    names = tuple(stage.name for stage in snapshot.stages)
    if names != CANONICAL_STAGE_NAMES:
        msg = f"review stages must be {CANONICAL_STAGE_NAMES}, got {names}"
        raise ValueError(msg)
    for stage in snapshot.stages:
        if not stage.observable:
            msg = f"review stage {stage.name!r} must be observable in the run manifest"
            raise ValueError(msg)
    return snapshot
