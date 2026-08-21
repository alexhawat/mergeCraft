"""Immutable ``ReviewSnapshot`` shared by CLI, Action, and SCM (#380).

Exports:
    CANONICAL_STAGE_NAMES: Ordered review stages every entry point must run.
    ReviewEntry: Which surface admitted the snapshot.
    ReviewSnapshot: Frozen, schema-validated review input.
    ReviewStageName: One canonical stage name.
    ReviewStageSpec: Per-stage timeout and observability.
    canonical_review_snapshot: Build a snapshot with canonical stages.
    snapshot_manifest_stages: Stage rows for the run manifest.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# D12: both fields survive (CLI JSON 1.0.0, agent JSONL 1). Do not import the
# CLI constants here — review must not depend on cli/.
_SNAPSHOT_SCHEMA_VERSION = "1.0.0"
_SNAPSHOT_PROTOCOL_VERSION = "1"

ReviewEntry = Literal["cli", "action", "scm"]
ReviewStageName = Literal["materialize", "analyze", "review", "publish"]

CANONICAL_STAGE_NAMES: tuple[ReviewStageName, ...] = (
    "materialize",
    "analyze",
    "review",
    "publish",
)

DEFAULT_STAGE_TIMEOUTS_MS: dict[ReviewStageName, int] = {
    "materialize": 120_000,
    "analyze": 300_000,
    "review": 600_000,
    "publish": 120_000,
}


class ReviewStageSpec(BaseModel):
    """One independently timeoutable, manifest-observable review stage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: ReviewStageName
    timeout_ms: int = Field(gt=0)
    observable: bool = True


class ReviewSnapshot(BaseModel):
    """Immutable review input for every entry point (#380).

    ``schema_version`` and ``protocol_version`` both survive (D12): CLI JSON
    keeps ``1.0.0``, agent JSONL keeps ``1``. File 8 RV5 pins the adapter, not
    a single survivor.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = _SNAPSHOT_SCHEMA_VERSION
    protocol_version: str = _SNAPSHOT_PROTOCOL_VERSION
    entry: ReviewEntry
    mode: str = "Review"
    stages: tuple[ReviewStageSpec, ...]
    source: str | None = None
    replay_key: str | None = None


def canonical_review_snapshot(
    *,
    entry: ReviewEntry,
    mode: str = "Review",
    source: str | None = None,
    replay_key: str | None = None,
) -> ReviewSnapshot:
    """Return a frozen snapshot with the canonical stage set."""
    stages = tuple(
        ReviewStageSpec(name=name, timeout_ms=DEFAULT_STAGE_TIMEOUTS_MS[name])
        for name in CANONICAL_STAGE_NAMES
    )
    return ReviewSnapshot(
        entry=entry,
        mode=mode,
        stages=stages,
        source=source,
        replay_key=replay_key,
    )


def snapshot_manifest_stages(snapshot: ReviewSnapshot) -> tuple[dict[str, object], ...]:
    """Stage rows the run manifest records for observability."""
    return tuple(
        {
            "name": stage.name,
            "timeout_ms": stage.timeout_ms,
            "observable": stage.observable,
        }
        for stage in snapshot.stages
    )
