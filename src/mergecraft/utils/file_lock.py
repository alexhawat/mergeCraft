"""Cancellation-aware acquisition for synchronous advisory file locks.

Exports:
    acquire_file_lock: Acquire an exclusive lock without trapping a cancelled worker.
"""

from __future__ import annotations

import fcntl
import time

from mergecraft.utils.process_scope import check_process_cancelled


def acquire_file_lock(fd: int) -> None:
    """Acquire ``fd`` exclusively, checking operation cancellation while waiting.

    The caller retains ownership of the descriptor and releases the acquired lock.
    """
    while True:
        check_process_cancelled()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            time.sleep(0.025)
