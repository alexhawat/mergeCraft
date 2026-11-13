"""Run synchronous subprocess work without abandoning it on async cancellation.

Exports:
    run_blocking: Offload work and join cancellation cleanup before returning.
    run_blocking_cleanup: Finish required cleanup before propagating cancellation.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
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
    worker_started = threading.Event()

    def invoke() -> _T:
        # Set this before checking cancellation: a worker racing queued
        # cancellation must either be joined or refuse to call user work.
        worker_started.set()
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
                if scope.cancelled.is_set() and not worker_started.is_set():
                    # A queued invocation owns no running work. If the executor
                    # starts it concurrently, invoke's cancellation check still
                    # prevents user work from starting after this response.
                    worker.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await worker

        cleanup_task = asyncio.create_task(cleanup())
        while not cleanup_task.done():
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(cleanup_task)
        cleanup_task.result()
        raise


async def run_blocking_cleanup(
    function: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs
) -> _T:
    """Finish required cleanup even when cancelled before its worker starts.

    Use only for cleanup of an already-entered mutation boundary. Unlike an
    ordinary queued operation, this work must finish before shared state or
    its lock is released. Cancellation is propagated after cleanup completes.
    """
    cleanup = asyncio.create_task(run_blocking(function, *args, **kwargs))
    cancelled = False
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            cancelled = True
    result = cleanup.result()
    if cancelled:
        raise asyncio.CancelledError
    return result
