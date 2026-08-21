"""Single review engine over one ``ReviewSnapshot`` (#380).

Exports:
    ReviewEngineResult: Snapshot plus canonical stage timeouts for one run.
    run_from_snapshot: Bind a snapshot into the shared engine.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

from mergecraft.review.snapshot import (
    CANONICAL_STAGE_NAMES,
    ReviewSnapshot,
    ReviewStageName,
    snapshot_manifest_stages,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ReviewEngineResult:
    """Bound snapshot that callers must execute rather than discard."""

    snapshot: ReviewSnapshot
    stages: tuple[dict[str, object], ...]
    stages_ran: tuple[ReviewStageName, ...]

    def timeout_s(self, name: ReviewStageName) -> float:
        """Return the stage timeout in seconds."""
        return self.snapshot.timeout_ms_for(name) / 1000.0

    async def run(
        self,
        execute: Callable[..., Awaitable[T]],
        /,
        **kwargs: Any,
    ) -> T:
        """Run ``execute`` under the snapshot's ``review`` stage timeout."""
        return await asyncio.wait_for(execute(**kwargs), timeout=self.timeout_s("review"))


def run_from_snapshot(snapshot: ReviewSnapshot) -> ReviewEngineResult:
    """Bind ``snapshot`` as the shared review engine input.

    CLI, Action, and SCM call this with the same type. Stage names, per-stage
    timeouts, and manifest rows live on the returned result so a second
    execution path cannot skip the contract. Pydantic validators on
    :class:`ReviewSnapshot` already refuse non-canonical stages.
    """
    return ReviewEngineResult(
        snapshot=snapshot,
        stages=snapshot_manifest_stages(snapshot),
        stages_ran=CANONICAL_STAGE_NAMES,
    )
