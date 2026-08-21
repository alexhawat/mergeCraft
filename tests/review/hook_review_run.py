"""Test-only adapter: four closures → ``ReviewRun``. Not a product export."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

R = TypeVar("R")
T = TypeVar("T")


@dataclass(slots=True)
class HookReviewRun(Generic[R, T]):
    """Wrap four stage callables as a ``ReviewRun`` for engine unit tests."""

    materialize_hook: Callable[[], Awaitable[object]]
    analyze_hook: Callable[[], Awaitable[object]]
    review_hook: Callable[[], Awaitable[R]]
    publish_hook: Callable[[R], Awaitable[T]]

    async def materialize(self) -> object:
        return await self.materialize_hook()

    async def analyze(self) -> object:
        return await self.analyze_hook()

    async def review(self) -> R:
        return await self.review_hook()

    async def publish(self, review_out: R) -> T:
        return await self.publish_hook(review_out)
