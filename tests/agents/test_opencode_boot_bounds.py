"""OpenCode serve boot must be bounded, drained from spawn, and reaped.

Two distinct hangs share ``_boot_opencode_server``:

* **event-loop block** — boot reads stdout with a blocking ``readline()`` on
  the event loop and only registers the process group after the URL, so a
  child that holds stdout open without a newline blocks the whole loop and is
  invisible to run-level cleanup.
* **stderr-before-URL** — boot never reads stderr until the URL arrives, so a
  server that logs enough to fill the pipe buffer blocks in ``write()`` and
  never prints its URL. A bounded stdout read alone still times out here.

The contract is that boot is run off-loop, registers the group at spawn,
drains both pipes from spawn, waits on an event with a deadline, and kills,
unregisters and reaps on timeout, early exit and cancellation.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING, Any

import pytest
from tests.agents.conftest import make_agent_run_context

import mergecraft.agents.opencode as oc

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

# A child that never prints a newline and never exits on its own.
_NO_NEWLINE_CHILD = (
    "import sys, time\n"
    "sys.stdout.write('opencode server booting without a newline')\n"
    "sys.stdout.flush()\n"
    "time.sleep(600)\n"
)

# A child that fills stderr *before* it prints its listening URL.
_N9_CHILD = (
    "import sys, time\n"
    "chunk = 'e' * 1024 + '\\n'\n"
    "for _ in range(4000):\n"
    "    sys.stderr.write('flood ' + chunk)\n"
    "sys.stderr.flush()\n"
    "sys.stdout.write('opencode server listening on http://127.0.0.1:54321/\\n')\n"
    "sys.stdout.flush()\n"
    "time.sleep(600)\n"
)

_BOOT_BOUND_S = 10.0
_RUN_BOUND_S = 45.0
_KILL_AFTER_S = 1.0


class _SubprocessShim:
    """Proxy the stdlib ``subprocess`` module but redirect ``Popen`` locally.

    Patching ``subprocess.Popen`` on the module object would change it process
    wide for every other thread; this keeps the swap scoped to the driver.
    """

    def __init__(self, popen: Callable[..., Any]) -> None:
        self._popen = popen

    def __getattr__(self, name: str) -> Any:
        return getattr(subprocess, name)

    def Popen(self, *args: Any, **kwargs: Any) -> Any:
        return self._popen(*args, **kwargs)


class _FakeClock:
    """A clock whose values advance far past any deadline on every read."""

    def __init__(self, step: float = 40.0) -> None:
        self._now = 0.0
        self._step = step

    def time(self) -> float:
        self._now += self._step
        return self._now

    def monotonic(self) -> float:
        self._now += self._step
        return self._now

    def sleep(self, seconds: float) -> None:
        del seconds


class _FakeStream:
    def __init__(self, order: list[str], label: str, lines: list[bytes]) -> None:
        self._order = order
        self._label = label
        self._lines = list(lines)
        self._lock = threading.Lock()

    def _first_read(self) -> None:
        self._order.append(f"read-{self._label}")

    def readline(self) -> bytes:
        with self._lock:
            self._first_read()
            if self._lines:
                return self._lines.pop(0)
            return b""

    def read(self) -> bytes:
        with self._lock:
            self._first_read()
            data = b"".join(self._lines)
            self._lines = []
            return data


class _FakeServeProc:
    """A ``Popen`` look-alike that records registration/read/kill ordering."""

    def __init__(
        self,
        order: list[str],
        *,
        url: bytes | None = b"listening on http://127.0.0.1:41235/\n",
    ) -> None:
        self.pid = 424_242
        self.stdout = _FakeStream(order, "stdout", [url] if url is not None else [])
        self.stderr = _FakeStream(order, "stderr", [])
        self.wait_calls = 0
        self.kill_calls = 0

    def poll(self) -> None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.wait_calls += 1
        return 0

    def kill(self) -> None:
        self.kill_calls += 1


def _shim_popen(monkeypatch: MonkeyPatch, factory: Callable[..., Any]) -> None:
    monkeypatch.setattr(oc, "subprocess", _SubprocessShim(factory))


def _spawn_real_child(
    monkeypatch: MonkeyPatch,
    children: list[subprocess.Popen[bytes]],
    script: str,
) -> subprocess.Popen[bytes]:
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    children.append(proc)

    def _factory(cmd: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        del cmd, kwargs
        return proc

    _shim_popen(monkeypatch, _factory)
    return proc


def _kill(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)
    for stream in (proc.stdout, proc.stderr):
        if stream is not None:
            stream.close()


@pytest.fixture
def children() -> Iterator[list[subprocess.Popen[bytes]]]:
    spawned: list[subprocess.Popen[bytes]] = []
    yield spawned
    for proc in spawned:
        _kill(proc)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True


# ---------------------------------------------------------------------------
# P5a — registration ordering and reaping (fake process; no real child)
# ---------------------------------------------------------------------------


def test_boot_registers_the_group_before_the_first_stdout_read(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Cleanup cannot find a hung boot that registers only after the URL."""
    order: list[str] = []
    proc = _FakeServeProc(order)
    _shim_popen(monkeypatch, lambda *_a, **_k: proc)
    registered: list[int] = []

    def _register(pid: int) -> None:
        registered.append(pid)
        order.append("register")

    monkeypatch.setattr(oc, "register_process_group", _register)
    monkeypatch.setattr(oc, "unregister_process_group", lambda _pid: order.append("unregister"))
    monkeypatch.setattr(oc, "kill_process_group", lambda _pid: order.append("kill"))

    handle = oc._boot_opencode_server(cli="/usr/bin/opencode", env={}, cwd=str(tmp_path))

    assert registered == [proc.pid]
    first_read = next(index for index, item in enumerate(order) if item.startswith("read-"))
    assert order.index("register") < first_read, (
        f"the process group must be registered at spawn, before the first read: {order}"
    )
    handle.close()
    assert "unregister" in order
    assert proc.wait_calls >= 1, "the group must be reaped on close"


def test_boot_failure_path_unregisters_and_reaps(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """A boot that never prints a URL must kill, unregister and reap."""
    order: list[str] = []
    proc = _FakeServeProc(order, url=None)
    _shim_popen(monkeypatch, lambda *_a, **_k: proc)
    monkeypatch.setattr(oc, "register_process_group", lambda _pid: order.append("register"))
    monkeypatch.setattr(oc, "unregister_process_group", lambda _pid: order.append("unregister"))
    monkeypatch.setattr(oc, "kill_process_group", lambda _pid: order.append("kill"))
    monkeypatch.setattr(oc, "time", _FakeClock())

    with pytest.raises(RuntimeError):
        oc._boot_opencode_server(cli="/usr/bin/opencode", env={}, cwd=str(tmp_path))

    assert "kill" in order
    assert "unregister" in order, f"a failed boot must unregister its group: {order}"
    assert proc.wait_calls >= 1, "a failed boot must reap the child"


def test_boot_keeps_its_synchronous_signature(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``lambda **kwargs: handle`` monkeypatches must stay valid (AR-D4)."""
    order: list[str] = []
    proc = _FakeServeProc(order)
    _shim_popen(monkeypatch, lambda *_a, **_k: proc)
    monkeypatch.setattr(oc, "register_process_group", lambda _pid: None)
    monkeypatch.setattr(oc, "unregister_process_group", lambda _pid: None)
    monkeypatch.setattr(oc, "kill_process_group", lambda _pid: None)

    result = oc._boot_opencode_server(cli="/usr/bin/opencode", env={}, cwd=str(tmp_path))

    assert not asyncio.iscoroutine(result), "boot must remain synchronous"
    assert result.base_url == "http://127.0.0.1:41235"
    result.close()


# ---------------------------------------------------------------------------
# N9 — stderr fills the pipe before the URL
# ---------------------------------------------------------------------------


def test_boot_succeeds_when_stderr_fills_the_pipe_before_the_url(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    children: list[subprocess.Popen[bytes]],
) -> None:
    """Distinct from the event-loop hang: stderr must be read from spawn."""
    child = _spawn_real_child(monkeypatch, children, _N9_CHILD)
    monkeypatch.setattr(oc, "register_process_group", lambda _pid: None)
    monkeypatch.setattr(oc, "unregister_process_group", lambda _pid: None)

    outcome: dict[str, Any] = {}

    def _target() -> None:
        try:
            outcome["handle"] = oc._boot_opencode_server(
                cli="/usr/bin/opencode", env={}, cwd=str(tmp_path)
            )
        except Exception as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=_BOOT_BOUND_S)
    if thread.is_alive():
        _kill(child)
        pytest.fail(
            "boot never returned: stderr filled the pipe before the URL and was "
            "not drained from spawn"
        )

    assert "error" not in outcome, f"boot failed: {outcome.get('error')!r}"
    handle = outcome["handle"]
    assert handle.base_url == "http://127.0.0.1:54321"
    handle.close()


# ---------------------------------------------------------------------------
# P5b — the event loop stays alive while boot runs; cancel reaps the child
# ---------------------------------------------------------------------------


def _wire_run(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    children: list[subprocess.Popen[bytes]],
    script: str,
) -> tuple[Any, Any]:
    from mergecraft.agents.shared import AgentResult

    child = _spawn_real_child(monkeypatch, children, script)
    ctx = make_agent_run_context(tmp_path, resolved_model="anthropic/claude-sonnet-5")

    async def _install(_token: str | None = None) -> str:
        return "/usr/bin/opencode-stub"

    monkeypatch.setattr(oc, "_install", _install)
    monkeypatch.setattr(oc, "_capture_integrity_baseline", lambda _ctx: (tmp_path, "test-digest"))

    def _gate(result: Any, _baseline: Any) -> Any:
        return result

    monkeypatch.setattr(oc, "_apply_integrity_gate", _gate)

    async def _fallback(*, cli: str, ctx: Any, env: dict[str, str]) -> Any:
        del cli, ctx, env
        return AgentResult(success=True, output="cli fallback")

    monkeypatch.setattr(oc, "_run_cli_fallback", _fallback)
    monkeypatch.setattr(oc, "register_process_group", lambda _pid: None)
    monkeypatch.setattr(oc, "unregister_process_group", lambda _pid: None)
    return ctx, child


def _spy_on_boot(monkeypatch: MonkeyPatch, starts: list[float], ends: list[float]) -> None:
    original = oc._boot_opencode_server

    def _spy(*args: Any, **kwargs: Any) -> Any:
        starts.append(time.monotonic())
        try:
            return original(*args, **kwargs)
        finally:
            ends.append(time.monotonic())

    monkeypatch.setattr(oc, "_boot_opencode_server", _spy)


async def test_run_keeps_the_event_loop_alive_during_boot(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    children: list[subprocess.Popen[bytes]],
) -> None:
    """A concurrent asyncio task must tick while ``_run`` is inside boot."""
    ctx, child = _wire_run(tmp_path, monkeypatch, children, _NO_NEWLINE_CHILD)
    starts: list[float] = []
    ends: list[float] = []
    _spy_on_boot(monkeypatch, starts, ends)

    ticks: list[float] = []
    run_task = asyncio.create_task(oc._run(ctx))

    async def _ticker() -> None:
        while len(ticks) < 500:
            await asyncio.sleep(0.02)
            ticks.append(time.monotonic())

    ticker = asyncio.create_task(_ticker())
    timer = threading.Timer(_KILL_AFTER_S, child.kill)
    timer.daemon = True
    timer.start()
    try:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(run_task), timeout=_RUN_BOUND_S)
    finally:
        timer.cancel()
        ticker.cancel()

    assert run_task.done(), "boot never returned"
    assert starts, "boot never ran"
    assert ends, "boot never finished"
    during_boot = [tick for tick in ticks if starts[0] < tick < ends[0]]
    assert during_boot, (
        "the event loop was blocked while boot ran: no concurrent task ticked "
        f"between boot start ({starts[0]:.2f}) and end ({ends[0]:.2f})"
    )


async def test_cancelling_run_mid_boot_kills_and_reaps_the_child(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    children: list[subprocess.Popen[bytes]],
) -> None:
    """Cancellation must reach boot and leave no live child pid."""
    ctx, child = _wire_run(tmp_path, monkeypatch, children, _NO_NEWLINE_CHILD)
    starts: list[float] = []
    ends: list[float] = []
    _spy_on_boot(monkeypatch, starts, ends)

    run_task = asyncio.create_task(oc._run(ctx))
    # Fail-safe: on the unfixed tree the loop is blocked and cannot be woken
    # from inside; the timer lets the blocked boot reach its own deadline.
    timer = threading.Timer(25.0, child.kill)
    timer.daemon = True
    timer.start()
    try:
        await asyncio.sleep(0.3)
        assert starts, "boot never started"
        cancel_at = time.monotonic()
        run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
            await asyncio.wait_for(run_task, timeout=_RUN_BOUND_S)

        assert run_task.done(), "cancelling _run must complete the task"
        assert not _pid_alive(child.pid), (
            "cancelling _run mid-boot must kill and reap the serve child"
        )
        assert ends, "boot never finished"
        assert cancel_at < ends[0], (
            "cancellation must reach boot before its deadline, not after boot returns"
        )
    finally:
        timer.cancel()
        if not run_task.done():
            run_task.cancel()
