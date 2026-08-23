"""`opencode serve` pipe draining (#449).

Boot reads the child's stdout only until the listening URL appears. With no
reader after that, the child blocks in ``write()`` once it fills the pipe
buffer (~64KB on Linux) and stops answering HTTP — a hang with no output, which
is indistinguishable from an unresponsive provider. PR #443 showed that shape:
9m51s of silence, then a timeout whose exception stringified to nothing.

These tests use a real subprocess because the defect is in OS pipe behaviour;
a stubbed stream cannot exhibit it.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

import mergecraft.agents.opencode as oc

if TYPE_CHECKING:
    from collections.abc import Iterator

# Comfortably past the 64KB pipe buffer: ~820KB.
_FLOOD = (
    "import sys\n"
    "for _ in range(20000):\n"
    "    print('x' * 40)\n"
    "print('SENTINEL-DONE')\n"
    "sys.stdout.flush()\n"
)


@pytest.fixture
def reap() -> Iterator[list[subprocess.Popen[bytes]]]:
    """Kill any process a test leaves blocked, so nothing outlives the run."""
    spawned: list[subprocess.Popen[bytes]] = []
    yield spawned
    for proc in spawned:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()


def _spawn(reap: list[subprocess.Popen[bytes]]) -> subprocess.Popen[bytes]:
    proc = subprocess.Popen(
        [sys.executable, "-c", _FLOOD],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    reap.append(proc)
    return proc


def test_a_chatty_server_runs_to_completion_when_drained(
    reap: list[subprocess.Popen[bytes]],
) -> None:
    """The fix: a drained child writes past the pipe buffer and finishes."""
    proc = _spawn(reap)
    handle = oc._ServerHandle(base_url="http://127.0.0.1:1", proc=proc)
    handle.start_draining()

    assert proc.wait(timeout=30) == 0
    for thread in handle._drains:
        thread.join(timeout=5)
    assert "SENTINEL-DONE" in handle.recent_output()


def test_an_undrained_server_blocks_on_a_full_pipe(
    reap: list[subprocess.Popen[bytes]],
) -> None:
    """Negative control — without draining the same child never finishes.

    This is the #443 hang in miniature. If this test ever starts passing
    without ``start_draining``, the buffer assumption changed and the guard
    above is no longer proving anything.
    """
    proc = _spawn(reap)
    oc._ServerHandle(base_url="http://127.0.0.1:1", proc=proc)  # no start_draining()

    with pytest.raises(subprocess.TimeoutExpired):
        proc.wait(timeout=5)
    assert proc.poll() is None, "child should still be blocked writing to a full pipe"


def test_recent_output_is_bounded(reap: list[subprocess.Popen[bytes]]) -> None:
    """The tail is a diagnostic buffer, not an unbounded log sink."""
    proc = _spawn(reap)
    handle = oc._ServerHandle(base_url="http://127.0.0.1:1", proc=proc)
    handle.start_draining()
    proc.wait(timeout=30)
    for thread in handle._drains:
        thread.join(timeout=5)

    lines = handle.recent_output().splitlines()
    assert 0 < len(lines) <= oc._SERVER_LOG_TAIL_LINES


def test_recent_output_is_empty_before_anything_is_drained() -> None:
    """A handle with no draining started reports nothing, and does not raise."""

    class _Fake:
        stdout = None
        stderr = None
        pid = -1

    handle = oc._ServerHandle(base_url="http://127.0.0.1:1", proc=_Fake())  # type: ignore[arg-type]
    handle.start_draining()
    assert handle.recent_output() == ""
