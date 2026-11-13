"""Run synchronous subprocess work without abandoning it on async cancellation.

Exports:
    run_blocking: Offload work and join cancellation cleanup before returning.
"""

from __future__ import annotations

import asyncio
import contextlib
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, ParamSpec, TypeVar

from mergecraft.utils.process_scope import (
    ProcessGroupScope,
    bind_process_group_scope,
    check_process_cancelled,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_P = ParamSpec("_P")
_T = TypeVar("_T")


async def run_blocking(function: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
    """Run a synchronous operation off-loop and wait for its cancellation cleanup.

    Registered child process groups belong only to this invocation. Cancellation
    kills those groups, then joins the worker before a caller can reset shared
    state or rebaseline a checkout. Repeated cancellation cannot detach cleanup.
    Synchronous I/O that cannot be interrupted must finish (or reach its own
    timeout) before cleanup returns; its late result is never published.
    """
    scope = ProcessGroupScope()

    def invoke() -> _T:
        with bind_process_group_scope(scope):
            check_process_cancelled()
            result = function(*args, **kwargs)
            check_process_cancelled()
            return result

    worker = asyncio.create_task(asyncio.to_thread(invoke))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:

        async def cleanup() -> None:
            # The default executor may be full of the very workers we must stop.
            # Join this short-lived cleanup executor only after its work has finished.
            try:
                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="mcp-cancel") as executor:
                    await asyncio.get_running_loop().run_in_executor(executor, scope.cancel)
            finally:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await worker

        cleanup_task = asyncio.create_task(cleanup())
        while not cleanup_task.done():
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(cleanup_task)
        cleanup_task.result()
        raise
