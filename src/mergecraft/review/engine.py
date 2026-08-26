"""Shared four-stage review runner over one ``ReviewSnapshot`` (#380).

Exports:
    ReviewEngine: Stage machine for materialize / analyze / review / publish.
    ReviewEngineResult: Snapshot plus stages that actually completed.
    ReviewRun: Protocol implemented by Action and offline drivers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar

from mergecraft.review.snapshot import (
    ReviewSnapshot,
    ReviewStageName,
    ReviewStageSpec,
)

TimeoutMap = Mapping[ReviewStageName, float]
OnTimeout = Callable[[ReviewStageName], None]
OnStage = Callable[[ReviewStageName], None]

R = TypeVar("R")
S = TypeVar("S")
T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)


class _TimeoutUnset:
    """Sentinel: derive the stage budget from the snapshot / overrides map."""


_TIMEOUT_UNSET = _TimeoutUnset()


class ReviewRun(Protocol[R, T_co]):
    """Stage driver for one engine run — methods, not closed-over callbacks."""

    async def materialize(self) -> object: ...

    async def analyze(self) -> object: ...

    async def review(self) -> R: ...

    async def publish(self, review_out: R) -> T_co: ...


@dataclass(frozen=True, slots=True)
class ReviewEngineResult(Generic[T]):
    """Outcome of one engine run — ``stages_ran`` is recorded after each stage."""

    snapshot: ReviewSnapshot
    stages: tuple[ReviewStageSpec, ...]
    stages_ran: tuple[ReviewStageName, ...]
    output: T | None = None

    def published_or(self, missing: T) -> T:
        """Return publish output, or ``missing`` when the stage produced none."""
        output = self.output
        if output is None:
            return missing
        return output


@dataclass(slots=True)
class ReviewEngine(Generic[T]):
    """Execute the canonical review stages with per-stage timeouts."""

    snapshot: ReviewSnapshot
    _ran: list[ReviewStageName] = field(default_factory=list, init=False, repr=False)
    _on_timeout: OnTimeout | None = field(default=None, init=False, repr=False)
    _on_stage: OnStage | None = field(default=None, init=False, repr=False)

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

    def set_on_stage(self, handler: OnStage | None) -> None:
        """Install a handler invoked when a stage starts (before the hook runs)."""
        self._on_stage = handler

    def _spec(self, name: ReviewStageName) -> ReviewStageSpec:
        for stage in self.snapshot.stages:
            if stage.name == name:
                return stage
        raise KeyError(name)

    def _timeout_for(
        self,
        name: ReviewStageName,
        timeouts: TimeoutMap | None,
    ) -> float | None:
        if timeouts is not None and name in timeouts:
            return timeouts[name]
        if not self._spec(name).engine_enforced:
            return None
        return self.timeout_s(name)

    async def run_stage(
        self,
        name: ReviewStageName,
        hook: Callable[[], Awaitable[S]],
        *,
        timeout_s: float | _TimeoutUnset | None = _TIMEOUT_UNSET,
        timeouts: TimeoutMap | None = None,
    ) -> S:
        """Await ``hook`` under the stage timeout; record ``name`` only on success."""
        on_stage = self._on_stage
        if on_stage is not None:
            on_stage(name)
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

    def result(self, output: T | None = None) -> ReviewEngineResult[T]:
        """Snapshot the stages that have completed so far."""
        return ReviewEngineResult(
            snapshot=self.snapshot,
            stages=self.stages,
            stages_ran=tuple(self._ran),
            output=output,
        )

    async def run(
        self,
        driver: ReviewRun[R, T],
        /,
        *,
        timeouts: TimeoutMap | None = None,
        on_timeout: OnTimeout | None = None,
    ) -> ReviewEngineResult[T]:
        """Run materialize → analyze → review → publish in order."""
        self._ran.clear()
        self._on_timeout = on_timeout
        await self.run_stage("materialize", driver.materialize, timeouts=timeouts)
        await self.run_stage("analyze", driver.analyze, timeouts=timeouts)
        review_out = await self.run_stage("review", driver.review, timeouts=timeouts)

        async def _publish() -> T:
            return await driver.publish(review_out)

        output = await self.run_stage("publish", _publish, timeouts=timeouts)
        return self.result(output)


__all__ = [
    "ReviewEngine",
    "ReviewEngineResult",
    "ReviewRun",
]
