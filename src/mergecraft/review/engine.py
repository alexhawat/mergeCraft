"""Shared four-stage review runner over one ``ReviewSnapshot`` (#380).

Exports:
    ReviewEngine: Stage machine for materialize / analyze / review / publish.
    ReviewEngineResult: Snapshot plus stages that actually completed.
    run_from_snapshot: Bind a snapshot into the shared engine.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from mergecraft.review.snapshot import (
    ReviewSnapshot,
    ReviewStageName,
    ReviewStageSpec,
)

StageHook = Callable[[], Awaitable[Any]]
PublishHook = Callable[[Any], Awaitable[Any]]
TimeoutMap = Mapping[ReviewStageName, float | None]
OnTimeout = Callable[[ReviewStageName], None]


class _TimeoutUnset:
    """Sentinel: derive the stage budget from the snapshot / overrides map."""


_TIMEOUT_UNSET = _TimeoutUnset()


@dataclass(frozen=True, slots=True)
class ReviewEngineResult:
    """Outcome of one engine run — ``stages_ran`` is recorded after each stage."""

    snapshot: ReviewSnapshot
    stages: tuple[ReviewStageSpec, ...]
    stages_ran: tuple[ReviewStageName, ...]
    output: Any = None


@dataclass(slots=True)
class ReviewEngine:
    """Execute the canonical review stages with per-stage timeouts."""

    snapshot: ReviewSnapshot
    _ran: list[ReviewStageName] = field(default_factory=list, init=False, repr=False)
    _on_timeout: OnTimeout | None = field(default=None, init=False, repr=False)

    @property
    def stages(self) -> tuple[ReviewStageSpec, ...]:
        """Return the snapshot's typed stage specs."""
        return self.snapshot.stages

    def timeout_s(self, name: ReviewStageName) -> float:
        """Return the snapshot timeout for ``name`` in seconds."""
        return self.snapshot.timeout_ms_for(name) / 1000.0

    def set_on_timeout(self, handler: OnTimeout | None) -> None:
        """Install a handler invoked when a stage ``wait_for`` times out."""
        self._on_timeout = handler

    def _timeout_for(
        self,
        name: ReviewStageName,
        timeouts: TimeoutMap | None,
    ) -> float | None:
        if timeouts is not None and name in timeouts:
            return timeouts[name]
        return self.timeout_s(name)

    async def run_stage(
        self,
        name: ReviewStageName,
        hook: StageHook,
        *,
        timeout_s: float | _TimeoutUnset | None = _TIMEOUT_UNSET,
        timeouts: TimeoutMap | None = None,
    ) -> Any:
        """Await ``hook`` under the stage timeout; record ``name`` only on success."""
        if isinstance(timeout_s, _TimeoutUnset):
            budget = self._timeout_for(name, timeouts)
        else:
            budget = timeout_s
        try:
            if budget is None:
                value = await hook()
            else:
                value = await asyncio.wait_for(hook(), timeout=budget)
        except TimeoutError:
            handler = self._on_timeout
            if handler is None:
                from mergecraft.utils.process_group import kill_all_active_process_groups

                kill_all_active_process_groups()
            else:
                handler(name)
            raise
        self._ran.append(name)
        return value

    def result(self, output: Any = None) -> ReviewEngineResult:
        """Snapshot the stages that have completed so far."""
        return ReviewEngineResult(
            snapshot=self.snapshot,
            stages=self.stages,
            stages_ran=tuple(self._ran),
            output=output,
        )

    async def run(
        self,
        *,
        materialize: StageHook,
        analyze: StageHook,
        review: StageHook,
        publish: PublishHook,
        timeouts: TimeoutMap | None = None,
        on_timeout: OnTimeout | None = None,
    ) -> ReviewEngineResult:
        """Run materialize → analyze → review → publish in order."""
        self._ran.clear()
        if on_timeout is not None:
            self._on_timeout = on_timeout
        await self.run_stage("materialize", materialize, timeouts=timeouts)
        await self.run_stage("analyze", analyze, timeouts=timeouts)
        review_out = await self.run_stage("review", review, timeouts=timeouts)

        async def _publish() -> Any:
            return await publish(review_out)

        output = await self.run_stage("publish", _publish, timeouts=timeouts)
        return self.result(output)

    def run_sync(
        self,
        *,
        materialize: StageHook,
        analyze: StageHook,
        review: StageHook,
        publish: PublishHook,
        timeouts: TimeoutMap | None = None,
        on_timeout: OnTimeout | None = None,
    ) -> ReviewEngineResult:
        """Synchronous wrapper for SCM and other non-async callers."""
        return asyncio.run(
            self.run(
                materialize=materialize,
                analyze=analyze,
                review=review,
                publish=publish,
                timeouts=timeouts,
                on_timeout=on_timeout,
            )
        )


def run_from_snapshot(snapshot: ReviewSnapshot) -> ReviewEngine:
    """Bind ``snapshot`` as the shared review engine.

    CLI, Action, and SCM call this with the same type. Stage timeouts live
    on the snapshot; ``stages_ran`` is filled only after ``run`` / ``run_stage``.
    """
    return ReviewEngine(snapshot=snapshot)


__all__ = [
    "ReviewEngine",
    "ReviewEngineResult",
    "run_from_snapshot",
]
