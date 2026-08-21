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

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# D12: both fields survive (CLI JSON 1.0.0, agent JSONL 1). CLI aliases these;
# review must not import cli/.
REVIEW_SCHEMA_VERSION = "1.0.0"
REVIEW_PROTOCOL_VERSION = "1"

ReviewEntry = Literal["cli", "action", "scm"]
ReviewStageName = Literal["materialize", "analyze", "review", "publish"]

CANONICAL_STAGE_NAMES: tuple[ReviewStageName, ...] = (
    "materialize",
    "analyze",
    "review",
    "publish",
)

# Align with Action setup (10m), analyzer_run (10m), and payload agent (1h).
DEFAULT_STAGE_TIMEOUTS_MS: dict[ReviewStageName, int] = {
    "materialize": 600_000,
    "analyze": 600_000,
    "review": 3_600_000,
    "publish": 120_000,
}

_ALLOWED_MODES: frozenset[str] = frozenset({"Review", "IncrementalReview"})


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

    schema_version: str = REVIEW_SCHEMA_VERSION
    protocol_version: str = REVIEW_PROTOCOL_VERSION
    entry: ReviewEntry
    mode: str = "Review"
    stages: tuple[ReviewStageSpec, ...]
    source: str | None = None
    replay_key: str | None = None

    @model_validator(mode="after")
    def _enforce_canonical_contract(self) -> Self:
        if self.mode not in _ALLOWED_MODES:
            msg = f"unsupported review mode {self.mode!r}"
            raise ValueError(msg)
        names = tuple(stage.name for stage in self.stages)
        if names != CANONICAL_STAGE_NAMES:
            msg = f"review stages must be {CANONICAL_STAGE_NAMES}, got {names}"
            raise ValueError(msg)
        for stage in self.stages:
            if not stage.observable:
                msg = f"review stage {stage.name!r} must be observable in the run manifest"
                raise ValueError(msg)
        return self

    def timeout_ms_for(self, name: ReviewStageName) -> int:
        """Return the snapshot timeout for a canonical stage."""
        for stage in self.stages:
            if stage.name == name:
                return stage.timeout_ms
        raise KeyError(name)


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
