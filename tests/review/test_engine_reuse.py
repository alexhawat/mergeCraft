"""GREEN — ReviewEngine timeout callback reset (AG7 / MCB-36)."""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.review.engine import ReviewEngine
from mergecraft.review.snapshot import (
    CANONICAL_STAGE_NAMES,
    ReviewSnapshot,
    ReviewStageName,
    ReviewStageSpec,
)


def _short_snapshot(*, review_ms: int = 10_000) -> ReviewSnapshot:
    stages = tuple(
        ReviewStageSpec(name=name, timeout_ms=review_ms if name == "review" else 10_000)
        for name in CANONICAL_STAGE_NAMES
    )
    return ReviewSnapshot(entry="cli", stages=stages)


class _StubDriver:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def materialize(self) -> None:
        self.calls.append("materialize")

    async def analyze(self) -> None:
        self.calls.append("analyze")

    async def review(self) -> dict[str, Any]:
        self.calls.append("review")
        return {"ok": True}

    async def publish(self, review_out: dict[str, Any]) -> dict[str, Any]:
        self.calls.append("publish")
        return review_out


@pytest.mark.asyncio
async def test_second_run_without_callback_does_not_call_the_first() -> None:
    engine = ReviewEngine(snapshot=_short_snapshot())
    driver = _StubDriver()
    first_calls: list[int] = []

    def on_first_timeout(name: ReviewStageName) -> None:
        first_calls.append(1)

    await engine.run(driver, on_timeout=on_first_timeout)
    await engine.run(_StubDriver(), on_timeout=None)
    assert first_calls == []
