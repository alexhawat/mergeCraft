"""Process-group spawn/kill helpers for agent CLI subprocesses (W9 / ``#14``).

Agents and MCP shell head their own session (``start_new_session=True``) so
timeout/cancel can ``killpg`` TERM → grace → KILL and reap grandchildren.
Active PIDs are tracked so the outer ``asyncio.wait_for`` path in ``main``
can tear the tree down when the blocking wait runs off-loop in a worker
thread. Canonical kill helper: :func:`kill_process_group`.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

_lock = threading.Lock()
_active_pgs: set[int] = set()


def register_process_group(pid: int | None) -> None:
    """Record an agent session leader so outer cancel can kill the group."""
    if pid is None:
        return
    with _lock:
        _active_pgs.add(pid)


def unregister_process_group(pid: int | None) -> None:
    if pid is None:
        return
    with _lock:
        _active_pgs.discard(pid)


def active_process_groups() -> frozenset[int]:
    with _lock:
        return frozenset(_active_pgs)


def _signal_process_group(pid: int, sig: signal.Signals) -> None:
    """Best-effort ``killpg`` with single-process fallbacks."""
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        return
    except PermissionError:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, sig)
    except AttributeError:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, sig)


def kill_process_group(pid: int | None, *, grace_s: float = 0.2) -> None:
    """Send SIGTERM to the process group, wait briefly, then SIGKILL.

    Reaches grandchildren spawned under ``start_new_session=True``. Shared by
    agent CLIs and MCP shell.
    """
    if pid is None:
        return
    _signal_process_group(pid, signal.SIGTERM)
    time.sleep(grace_s)
    _signal_process_group(pid, signal.SIGKILL)


def kill_process_groups(pids: set[int] | frozenset[int], *, grace_s: float = 0.2) -> None:
    """Batch TERM -> one grace -> KILL for many session leaders (no N-times sleep)."""
    leaders = {p for p in pids if isinstance(p, int)}
    if not leaders:
        return
    for pid in leaders:
        _signal_process_group(pid, signal.SIGTERM)
    time.sleep(grace_s)
    for pid in leaders:
        _signal_process_group(pid, signal.SIGKILL)


def kill_all_active_process_groups(*, grace_s: float = 0.2) -> None:
    """Kill every registered agent process group (outer ``wait_for`` timeout)."""
    kill_process_groups(active_process_groups(), grace_s=grace_s)


@contextmanager
def track_process_group(process: subprocess.Popen[Any]) -> Iterator[subprocess.Popen[Any]]:
    """Register ``process.pid`` for the lifetime of the ``with`` block."""
    pid = getattr(process, "pid", None)
    register_process_group(pid if isinstance(pid, int) else None)
    try:
        yield process
    finally:
        unregister_process_group(pid if isinstance(pid, int) else None)


def wait_or_kill_process_group(
    process: subprocess.Popen[Any],
    *,
    timeout: float | None,
) -> int:
    """``process.wait`` with group kill on ``TimeoutExpired``.

    The wait itself is intentional blocking I/O — callers that need the
    event loop to stay responsive should invoke the surrounding sync runner
    via ``asyncio.to_thread``.
    """
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pid = getattr(process, "pid", None)
        kill_process_group(pid if isinstance(pid, int) else None)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError, PermissionError, AttributeError):
                process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=1)
        raise


__all__ = [
    "active_process_groups",
    "kill_all_active_process_groups",
    "kill_process_group",
    "kill_process_groups",
    "register_process_group",
    "track_process_group",
    "unregister_process_group",
    "wait_or_kill_process_group",
]
