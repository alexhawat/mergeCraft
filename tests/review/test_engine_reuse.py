"""RED — ReviewEngine timeout callback reset (AG7 / MCB-36)."""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.review.engine import ReviewEngine

pytestmark = pytest.mark.xfail(
    reason="green after AG7: engine timeout callback reset",
    strict=False,
)


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
    engine = ReviewEngine()
    driver = _StubDriver()
    first_calls: list[int] = []

    async def on_first_timeout() -> None:
        first_calls.append(1)

    await engine.run(driver, on_timeout=on_first_timeout)
    await engine.run(_StubDriver(), on_timeout=None)
    assert first_calls == []
