"""Activity marker for agent idle detection."""

from __future__ import annotations

import time

_last_activity = time.perf_counter()


def mark_activity() -> None:
    global _last_activity
    _last_activity = time.perf_counter()


__all__ = ["mark_activity"]
