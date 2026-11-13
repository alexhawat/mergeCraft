"""Owned blocking tasks consume late failures without unhandled loop diagnostics."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.utils.blocking import run_blocking, run_blocking_cleanup

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@pytest.mark.parametrize("runner", [run_blocking, run_blocking_cleanup], ids=lambda fn: fn.__name__)
@pytest.mark.parametrize("cancellations", [0, 1, 3], ids=["error", "cancel", "repeated-cancel"])
async def test_owned_worker_failure_is_consumed(
    runner: Callable[..., Awaitable[None]], cancellations: int
) -> None:
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    diagnostics: list[dict[str, Any]] = []
    loop.set_exception_handler(lambda _loop, context: diagnostics.append(context))
    started = asyncio.Event()
    release, finished = threading.Event(), threading.Event()

    def work() -> None:
        loop.call_soon_threadsafe(started.set)
        assert release.wait(5)
        finished.set()
        raise RuntimeError("owned worker failed after cancellation")

    pending = asyncio.create_task(runner(work))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        for _ in range(cancellations):
            pending.cancel()
            await asyncio.sleep(0)
        assert not pending.done(), "owned work was detached before it finished"
        release.set()
        if cancellations and runner is run_blocking:
            with pytest.raises(asyncio.CancelledError):
                await pending
        else:
            with pytest.raises(RuntimeError, match="owned worker failed after cancellation"):
                await pending
        assert finished.is_set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not diagnostics, diagnostics
    finally:
        release.set()
        if not pending.done():
            with contextlib.suppress(asyncio.CancelledError, RuntimeError):
                await pending
        loop.set_exception_handler(previous_handler)
