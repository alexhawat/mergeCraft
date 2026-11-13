"""Bind child process groups to cancellable, nestable operations.

Context propagation into worker threads keeps registrations attached to every
owning operation. Cancelling a scope kills only its groups and rejects late
children; cancelling an outer operation also reaches children of inner scopes.

Exports:
    ProcessGroupScope: Thread-safe ownership and cancellation of process groups.
    bind_process_group_scope: Add an operation scope to the current context.
    current_process_group_scopes: Return all scopes owning this context's work.
    check_process_cancelled: Refuse work after any owning scope was cancelled.
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


class ProcessGroupScope:
    """Own process groups for one operation, including its worker threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pids: set[int] = set()
        self.cancelled = threading.Event()

    def add(self, pid: int) -> None:
        """Register a group, or kill it and raise cancellation after shutdown.

        Args:
            pid (int): Child process group leader registered immediately after spawn.

        Raises:
            asyncio.CancelledError: The operation was already cancelled.
        """
        from mergecraft.utils.process_group import kill_process_group

        with self._lock:
            cancelled = self.cancelled.is_set()
            if not cancelled:
                self._pids.add(pid)
        if cancelled:
            kill_process_group(pid)
            raise asyncio.CancelledError

    def remove(self, pid: int) -> None:
        """Forget a group when its owner has finished cleanup.

        Args:
            pid (int): Previously registered process group leader.
        """
        with self._lock:
            self._pids.discard(pid)

    def cancel(self) -> None:
        """Refuse further work and kill the currently registered groups.

        Examples:
            >>> scope = ProcessGroupScope()
            >>> scope.cancel()
            >>> scope.cancelled.is_set()
            True
        """
        from mergecraft.utils.process_group import kill_process_groups

        with self._lock:
            self.cancelled.set()
            pids = frozenset(self._pids)
            self._pids.clear()
        kill_process_groups(pids)


_SCOPES: ContextVar[tuple[ProcessGroupScope, ...]] = ContextVar("process_group_scopes", default=())


@contextmanager
def bind_process_group_scope(scope: ProcessGroupScope) -> Iterator[None]:
    """Bind a scope alongside any outer operation scopes.

    Args:
        scope (ProcessGroupScope): Operation that owns work in this context.

    Yields:
        None: The bound context; ownership is reset when the block ends.

    Examples:
        >>> scope = ProcessGroupScope()
        >>> with bind_process_group_scope(scope):
        ...     current_process_group_scopes() == (scope,)
        True
    """
    token = _SCOPES.set((*_SCOPES.get(), scope))
    try:
        yield
    finally:
        _SCOPES.reset(token)


def current_process_group_scopes() -> tuple[ProcessGroupScope, ...]:
    """Return the scopes owning work in the current context."""
    return _SCOPES.get()


def check_process_cancelled() -> None:
    """Raise cancellation before starting work or publishing its result.

    Raises:
        asyncio.CancelledError: At least one enclosing scope was cancelled.

    Examples:
        >>> check_process_cancelled()  # An unbound operation is not cancelled.
    """
    if any(scope.cancelled.is_set() for scope in _SCOPES.get()):
        raise asyncio.CancelledError
