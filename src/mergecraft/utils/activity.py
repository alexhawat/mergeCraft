"""Activity timeout helper for agent idle detection."""

from __future__ import annotations

import asyncio
import re
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_ACTIVITY_TIMEOUT_MS = 300_000
AGENT_ACTIVITY_TIMEOUT_MS = 900_000
DEFAULT_ACTIVITY_CHECK_INTERVAL_MS = 5_000

_DEBUG_TS_PREFIX = r"(?:\[\d{4}-\d{2}-\d{2}T[^\]]+\]\s+)?"
ACTIVITY_NOISE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"{_DEBUG_TS_PREFIX}\[mcp-proxy\]"),
    re.compile(rf"{_DEBUG_TS_PREFIX}» provider error detected"),
    re.compile(rf"{_DEBUG_TS_PREFIX}\[DEBUG\]\s+(?:spawn|process) activity "),
    re.compile(r"^::debug::(?:spawn|process) activity "),
)

_last_activity = time.perf_counter()


def mark_activity() -> None:
    global _last_activity
    _last_activity = time.perf_counter()


def get_idle_ms() -> int:
    return round((time.perf_counter() - _last_activity) * 1000)


def is_activity_noise(chunk: str | bytes) -> bool:
    text = chunk.decode("utf-8", errors="replace") if isinstance(chunk, bytes) else chunk
    if not text.strip():
        return True
    return all(
        (not trimmed) or any(pattern.search(trimmed) for pattern in ACTIVITY_NOISE_PATTERNS)
        for line in text.split("\n")
        for trimmed in [line.strip()]
    )


@dataclass(slots=True)
class ActivityTimeout:
    promise: asyncio.Future[None]
    _stop: Callable[[], None]
    _force_reject: Callable[[str], None]

    def stop(self) -> None:
        self._stop()

    def force_reject(self, reason: str) -> None:
        self._force_reject(reason)


def create_process_output_activity_timeout(
    *,
    timeout_ms: int = AGENT_ACTIVITY_TIMEOUT_MS,
    check_interval_ms: int = DEFAULT_ACTIVITY_CHECK_INTERVAL_MS,
) -> ActivityTimeout:
    """Watch process output activity; reject when idle longer than ``timeout_ms``."""
    mark_activity()
    loop = asyncio.get_running_loop()
    future: asyncio.Future[None] = loop.create_future()
    reject_armed = True
    original_stdout_write = sys.stdout.write
    original_stderr_write = sys.stderr.write

    def _on_write(original: Callable[..., int], stream: TextIO) -> Callable[..., int]:
        def wrapped(s: str) -> int:
            if not is_activity_noise(s):
                mark_activity()
            return original(s)

        return wrapped

    sys.stdout.write = _on_write(original_stdout_write, sys.stdout)  # type: ignore[method-assign]  # — monkey-patching stdout.write to intercept CI output; restored in _restore
    sys.stderr.write = _on_write(original_stderr_write, sys.stderr)  # type: ignore[method-assign]  # — monkey-patching stderr.write to intercept CI output; restored in _restore

    def _restore() -> None:
        sys.stdout.write = original_stdout_write  # type: ignore[method-assign]  # — restoring original stdout.write after interception
        sys.stderr.write = original_stderr_write  # type: ignore[method-assign]  # — restoring original stderr.write after interception

    async def _poll() -> None:
        nonlocal reject_armed
        while reject_armed and not future.done():
            await asyncio.sleep(check_interval_ms / 1000.0)
            idle = get_idle_ms()
            if reject_armed and idle > timeout_ms and not future.done():
                _restore()
                reject_armed = False
                future.set_exception(
                    TimeoutError(f"activity timeout: no output for {round(idle / 1000)}s")
                )
                return

    task = asyncio.create_task(_poll())

    def stop() -> None:
        nonlocal reject_armed
        reject_armed = False
        task.cancel()
        _restore()

    def force_reject(reason: str) -> None:
        nonlocal reject_armed
        if not reject_armed or future.done():
            return
        reject_armed = False
        task.cancel()
        _restore()
        future.set_exception(RuntimeError(reason))

    return ActivityTimeout(promise=future, _stop=stop, _force_reject=force_reject)


__all__ = [
    "ACTIVITY_NOISE_PATTERNS",
    "AGENT_ACTIVITY_TIMEOUT_MS",
    "DEFAULT_ACTIVITY_CHECK_INTERVAL_MS",
    "DEFAULT_ACTIVITY_TIMEOUT_MS",
    "ActivityTimeout",
    "create_process_output_activity_timeout",
    "get_idle_ms",
    "is_activity_noise",
    "mark_activity",
]
