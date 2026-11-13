"""Run-owned snapshots shared safely across asynchronous callers and event loops.

Exports:
    RunMemo: Coalesce duplicate reads and return independent copies of their values.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from concurrent.futures import Future
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Hashable

_T = TypeVar("_T")
_Key = tuple["Hashable", ...]


@dataclass(eq=False)
class _PendingRead:
    future: Future[Any]
    task: asyncio.Task[Any]
    loop: asyncio.AbstractEventLoop
    active: bool = True


async def _wait_shared(future: Future[Any]) -> Any:
    """Bridge completion to this loop without propagating waiter cancellation."""
    loop = asyncio.get_running_loop()
    waiting: asyncio.Future[Any] = loop.create_future()

    def complete(source: Future[Any]) -> None:
        if waiting.done():
            return
        if source.cancelled():
            waiting.cancel()
            return
        try:
            value = source.result()
        except BaseException as error:
            waiting.set_exception(error)
        else:
            waiting.set_result(value)

    def notify(source: Future[Any]) -> None:
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(complete, source)

    future.add_done_callback(notify)
    return await waiting


class RunMemo:
    """Cache one client's run snapshots without binding synchronization to a loop.

    Each key identifies one result type. Failed or cancelled reads are evicted;
    callers that need a stable fail-closed snapshot return a failure value instead.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[_Key, Any] = {}
        self._pending: dict[_Key, _PendingRead] = {}
        self._active: set[_PendingRead] = set()

    async def read(self, key: _Key, fetch: Callable[[], Awaitable[_T]]) -> _T:
        """Read once and copy the snapshot for each consumer.

        Args:
            key: Complete identity within this run/client, including relevant refs.
            fetch: Producer used only when no completed or pending read exists.

        Returns:
            An independent copy of the producer's result.

        Raises:
            BaseException: The producer failed or was cancelled; a later call may retry.
        """
        with self._lock:
            if key in self._values:
                # A key has the result type of its producer, shared by all consumers.
                return cast("_T", deepcopy(self._values[key]))
            entry = self._pending.get(key)
            owner = entry is None
            if entry is None:
                task = asyncio.current_task()
                assert task is not None
                entry = _PendingRead(Future(), task, asyncio.get_running_loop())
                self._pending[key] = entry
                self._active.add(entry)
        future = entry.future
        if not owner:
            value = await _wait_shared(future)
            # The shared key has the result type of its sole producer.
            return cast("_T", deepcopy(value))
        try:
            value = await fetch()
            snapshot = deepcopy(value)
            with self._lock:
                cancelled = future.cancelled()
                if not cancelled:
                    if self._pending.get(key) is entry:
                        self._values[key] = snapshot
                    future.set_result(snapshot)
            if cancelled:
                raise asyncio.CancelledError
            return deepcopy(value)
        except BaseException as error:
            with self._lock:
                if not future.done():
                    future.set_exception(error)
            raise
        finally:
            with self._lock:
                entry.active = False
                self._active.discard(entry)
                if self._pending.get(key) is entry:
                    del self._pending[key]

    def close(self) -> None:
        """End the current generation, settling readers and cancelling producers.

        Invalidated reads remain owned until they finish, so close also reaches
        producers no longer indexed by a cache key. Completed caller tasks are
        never cancelled after the read has returned. A later read starts a fresh
        generation, matching the owning client's reusable transport lifecycle.
        """
        with self._lock:
            self._values.clear()
            self._pending.clear()
            active = list(self._active)
            self._active.clear()
            for entry in active:
                entry.future.cancel()
        for entry in active:
            # A departed loop has no runnable producer; its readers are settled.
            with contextlib.suppress(RuntimeError):
                entry.loop.call_soon_threadsafe(self._cancel_active, entry)

    def _cancel_active(self, entry: _PendingRead) -> None:
        with self._lock:
            active = entry.active
        if active:
            entry.task.cancel()

    def clear(self, *, category: str | None = None) -> None:
        """Forget snapshots; an old in-flight read cannot repopulate the cache.

        Args:
            category: Clear only keys whose first component matches, or all keys.
        """
        with self._lock:
            for collection in (self._values, self._pending):
                for key in list(collection):
                    if category is None or key[0] == category:
                        del collection[key]
