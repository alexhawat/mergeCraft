"""A full stderr pipe must not deadlock an agent driver.

Every driver reads the child's stdout to EOF and only then touches stderr.
A child that writes enough stderr to fill the platform pipe buffer blocks in
``write()``, stops producing stdout, and the driver waits on stdout forever —
the registered process-group deadline is a mitigation, never a prevention.

The contract is that stderr is drained concurrently, from spawn, into a
bounded (tail-kept) buffer, and that the driver returns within a bounded time
with the stderr tail still reaching its diagnostics.

These cases use a real subprocess because the defect lives in OS pipe
behaviour; a stubbed stream cannot exhibit it.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import subprocess
import sys
import threading
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from tests.agents.conftest import make_agent_run_context

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

# Comfortably past every platform pipe buffer (macOS 16KB, Linux 64KB):
# ~4MB of stderr before the child attempts its stdout event.
_FLOOD_LINES = 4000
_SENTINEL = "STDERR-SENTINEL-TAIL"

# The whole driver must return well before this; a blocked driver never does.
_DRIVER_BOUND_S = 8.0

_DRAIN_HELPER_NAME = "start_stderr_drain"
_DRAIN_CAP_NAME = "STDERR_DRAIN_MAX_LINES"

# AR0 recorded the cap at 2,000 lines: >= the 20-line diagnostic tail and well
# above what ``is_retryable_cli_failure`` scans (the whole text).
_STDERR_DRAIN_CAP = 2000


def _flood_script(*, stdout_event: bool) -> str:
    """A child that fills stderr, then (optionally) emits its stdout event."""
    lines = [
        "import sys",
        "chunk = 'e' * 1024 + '\\n'",
        f"for _ in range({_FLOOD_LINES}):",
        "    sys.stderr.write('flood ' + chunk)",
        f"sys.stderr.write('{_SENTINEL}\\n')",
        "sys.stderr.flush()",
    ]
    if stdout_event:
        lines += [
            'sys.stdout.write(\'{"type": "result", "result": "ok"}\\n\')',
            "sys.stdout.flush()",
        ]
    lines.append("sys.exit(1)")
    return "\n".join(lines)


class _NullProcessGroup:
    """A no-op replacement for ``track_process_group`` (never signals a pid)."""

    def __init__(self, *_args: object, **_kwargs: object) -> None: ...

    def __enter__(self) -> None: ...

    def __exit__(self, *_args: object) -> bool:
        return False


def _kill(proc: subprocess.Popen[str]) -> None:
    """Best-effort kill + reap so nothing outlives a failing case."""
    if proc.poll() is None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)
    for stream in (proc.stdout, proc.stderr):
        if stream is not None:
            stream.close()


@pytest.fixture
def children() -> Iterator[list[subprocess.Popen[str]]]:
    """Reap any real child a failing case leaves blocked."""
    spawned: list[subprocess.Popen[str]] = []
    yield spawned
    for proc in spawned:
        _kill(proc)


class _DriverSpec(NamedTuple):
    name: str
    module_name: str
    invoke: Callable[[Any, Any, Path], Any]
    timeout_error: str


def _invoke_claude(module: Any, ctx: Any, tmp_path: Path) -> Any:
    return module._run_claude_once(
        cli="/usr/bin/claude",
        prompt="review this diff",
        ctx=ctx,
        mcp_config=str(tmp_path / "mcp.json"),
    )


def _invoke_codex(module: Any, ctx: Any, tmp_path: Path) -> Any:
    return module._run_codex_streaming(
        cmd=["codex", "exec", "--json", "review this diff"],
        ctx=ctx,
        model="gpt-5.6-sol",
        prompt="review this diff",
    )


def _invoke_gemini(module: Any, ctx: Any, tmp_path: Path) -> Any:
    return module._run_gemini_streaming(
        cmd=["gemini", "-p", "review this diff"],
        ctx=ctx,
        model="gemini-3.1-pro",
        prompt="review this diff",
    )


def _invoke_opencode(module: Any, ctx: Any, tmp_path: Path) -> Any:
    return module._run_opencode_cli_streaming(
        cmd=["opencode", "run", "--format", "json", "review this diff"],
        ctx=ctx,
        env={},
    )


_DRIVERS = (
    _DriverSpec("claude", "mergecraft.agents.claude", _invoke_claude, "claude CLI timed out"),
    _DriverSpec("codex", "mergecraft.agents.codex", _invoke_codex, "codex CLI timed out"),
    _DriverSpec("gemini", "mergecraft.agents.gemini", _invoke_gemini, "gemini CLI timed out"),
    _DriverSpec(
        "opencode", "mergecraft.agents.opencode", _invoke_opencode, "opencode run timed out"
    ),
)
_DRIVER_IDS = tuple(spec.name for spec in _DRIVERS)


def _spec(driver: str) -> _DriverSpec:
    for spec in _DRIVERS:
        if spec.name == driver:
            return spec
    msg = f"unknown driver: {driver}"
    raise AssertionError(msg)


def _spawn_child(children: list[subprocess.Popen[str]], script: str) -> subprocess.Popen[str]:
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    children.append(proc)
    return proc


def _patch_driver(
    monkeypatch: MonkeyPatch,
    spec: _DriverSpec,
    child: Any,
    *,
    wait_raises: bool = False,
) -> None:
    module = importlib.import_module(spec.module_name)
    monkeypatch.setattr(module, "spawn_agent_cli", lambda *_a, **_k: child)
    if hasattr(module, "_build_env"):
        monkeypatch.setattr(module, "_build_env", lambda _ctx: {})
    monkeypatch.setattr(module, "track_process_group", _NullProcessGroup)

    def _wait(process: Any, *, timeout: float | None = None) -> int:
        if wait_raises:
            raise subprocess.TimeoutExpired(cmd=spec.name, timeout=timeout or 1)
        return process.wait(timeout=timeout)

    monkeypatch.setattr(module, "wait_or_kill_process_group", _wait)


def _run_in_thread(call: Callable[[], Any], *, bound_s: float) -> tuple[dict[str, Any], Any]:
    outcome: dict[str, Any] = {}

    def _target() -> None:
        try:
            outcome["result"] = call()
        except Exception as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=bound_s)
    return outcome, thread


@pytest.mark.parametrize("driver", _DRIVER_IDS)
def test_driver_returns_when_stderr_is_filled_before_stdout(
    driver: str,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    children: list[subprocess.Popen[str]],
) -> None:
    """The child blocks in ``stderr.write`` until the driver reads stderr.

    The driver must drain stderr from spawn, so the child reaches its stdout
    event and exits; the sentinel tail must reach the failure diagnostics.
    """
    spec = _spec(driver)
    ctx = make_agent_run_context(tmp_path, resolved_model="anthropic/claude-sonnet-5")
    child = _spawn_child(children, _flood_script(stdout_event=True))
    _patch_driver(monkeypatch, spec, child)

    def _call() -> Any:
        return spec.invoke(importlib.import_module(spec.module_name), ctx, tmp_path)

    outcome, thread = _run_in_thread(_call, bound_s=_DRIVER_BOUND_S)
    if thread.is_alive():
        _kill(child)
        thread.join(timeout=10)
        pytest.fail(
            f"{driver}: driver never returned — stdout was read to EOF while the "
            "child filled stderr (a full stderr pipe deadlocks the child)"
        )

    assert "error" not in outcome, f"{driver} raised {outcome.get('error')!r}"
    result = outcome["result"]
    assert result.success is False
    assert _SENTINEL in (result.error or ""), (
        f"{driver}: the stderr tail must reach diagnostics, got {result.error!r}"
    )


@pytest.mark.parametrize("driver", _DRIVER_IDS)
def test_driver_timeout_path_still_returns_when_stderr_is_filled(
    driver: str,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    children: list[subprocess.Popen[str]],
) -> None:
    """A timeout after a stderr flood must still return a failed result.

    The drain thread must never outlive the process group; the driver reaches
    its ``TimeoutExpired`` handler once stdout reaches EOF.
    """
    spec = _spec(driver)
    ctx = make_agent_run_context(tmp_path, resolved_model="anthropic/claude-sonnet-5")
    child = _spawn_child(children, _flood_script(stdout_event=False))
    _patch_driver(monkeypatch, spec, child, wait_raises=True)

    def _call() -> Any:
        return spec.invoke(importlib.import_module(spec.module_name), ctx, tmp_path)

    outcome, thread = _run_in_thread(_call, bound_s=_DRIVER_BOUND_S)
    if thread.is_alive():
        _kill(child)
        thread.join(timeout=10)
        pytest.fail(f"{driver}: timeout path never returned — stderr was not drained from spawn")

    assert "error" not in outcome, f"{driver} raised {outcome.get('error')!r}"
    result = outcome["result"]
    assert result.success is False
    assert spec.timeout_error in (result.error or ""), result.error


# ---------------------------------------------------------------------------
# AR2 helper contract — the shared bounded, tail-kept stderr drain.
# ---------------------------------------------------------------------------


def _shared_module() -> Any:
    return importlib.import_module("mergecraft.agents.shared")


def _drain_helper() -> Any:
    shared = _shared_module()
    assert hasattr(shared, _DRAIN_HELPER_NAME), (
        "AR2 must add a bounded stderr drain helper to mergecraft.agents.shared "
        f"(expected `{_DRAIN_HELPER_NAME}`) per the AR-D2/AR-D3 decisions"
    )
    return getattr(shared, _DRAIN_HELPER_NAME)


def test_stderr_drain_cap_is_the_recorded_two_thousand_lines() -> None:
    """The cap is documented: 2,000 lines, tail-kept (AR0 recorded it)."""
    shared = _shared_module()
    assert hasattr(shared, _DRAIN_CAP_NAME), (
        f"AR2 must expose `{_DRAIN_CAP_NAME}` beside the drain helper"
    )
    assert getattr(shared, _DRAIN_CAP_NAME) == _STDERR_DRAIN_CAP


def test_drain_collects_a_stringio_fake_process_stream() -> None:
    """The helper accepts the ``io.StringIO`` fakes the cov suites use."""
    drain = _drain_helper()(io.StringIO("alpha\nbeta\ngamma\n"))
    drain.join(timeout=5)

    text = drain.text()
    assert "alpha" in text
    assert "beta" in text
    assert text.splitlines()[-1] == "gamma"


def test_drain_keeps_the_tail_when_the_stream_exceeds_the_cap() -> None:
    """A bounded buffer drops the oldest lines and keeps the newest."""
    shared = _shared_module()
    drain = _drain_helper()
    cap = getattr(shared, _DRAIN_CAP_NAME)
    payload = "\n".join(f"line-{index:05d}" for index in range(cap + 50)) + "\n"

    handle = drain(io.StringIO(payload))
    handle.join(timeout=5)
    lines = handle.text().splitlines()

    assert 0 < len(lines) <= cap
    assert lines[-1] == f"line-{cap + 49:05d}"
    assert lines[0] != "line-00000", "the oldest lines must be dropped"


def test_drain_tolerates_a_stream_that_closes_mid_read() -> None:
    """A pipe closed under the drain ends the thread without an exception."""

    class _ClosingStream:
        def __init__(self) -> None:
            self._lines = ["one\n", "two\n"]

        def readline(self) -> str:
            if self._lines:
                return self._lines.pop(0)
            raise ValueError("I/O operation on closed file")

    handle = _drain_helper()(_ClosingStream())
    handle.join(timeout=5)

    assert "one" in handle.text()
    assert "two" in handle.text()


def test_drain_accepts_a_read_only_fake_process_stream() -> None:
    """The cov fakes expose only ``read()``; the helper must still drain."""

    class _ReadOnlyStream:
        def __init__(self, text: str) -> None:
            self._text = text

        def read(self) -> str:
            return self._text

    handle = _drain_helper()(_ReadOnlyStream("tail-one\ntail-two\n"))
    handle.join(timeout=5)

    assert "tail-one" in handle.text()


# ---------------------------------------------------------------------------
# AR8.3(a) — ``text()`` must snapshot a live buffer without raising.
#
# ``join`` is bounded: a grandchild holding the stderr pipe open means the
# reader thread is still appending when the driver collects the tail. Before
# AR8.2 ``text()`` did ``"".join(self._lines)`` with no synchronisation, so
# iterating the ``deque`` while the reader appended could raise
# ``RuntimeError: deque mutated during iteration`` on exactly that path.
# ---------------------------------------------------------------------------

_RELEASE_READER_S = 5.0
_SNAPSHOT_PROBES = 200


class _StayOpenStream:
    """A stderr stream with no EOF until the test releases it.

    Mirrors a grandchild that keeps the child's stderr pipe open: ``readline``
    keeps returning lines, so the drain's reader thread is still active when a
    bounded ``join`` returns. The ``threading.Event`` bounds the shutdown wait
    — the test never sleeps for an unbounded time.
    """

    def __init__(self, stop: threading.Event) -> None:
        self._stop = stop
        self._index = 0

    def readline(self) -> str:
        if self._stop.is_set():
            self._stop.wait(timeout=_RELEASE_READER_S)
            return ""
        self._index += 1
        return f"line-{self._index:05d}\n"


def test_text_returns_tail_while_the_reader_is_still_appending() -> None:
    """An early ``join`` must not poison a snapshot of the live buffer.

    The reader never reaches EOF, so ``join(timeout=<short>)`` returns while it
    is still appending. Repeated ``text()`` calls must return the tail read so
    far — a string with no torn lines — and must never raise ``RuntimeError``.
    """
    stop = threading.Event()
    drain = _drain_helper()(_StayOpenStream(stop))
    try:
        drain.join(timeout=0.05)
        assert drain._thread.is_alive(), (
            "the stream has no EOF, so the bounded join must return with the "
            "reader still active (the path this pin targets)"
        )

        for _ in range(_SNAPSHOT_PROBES):
            snapshot = drain.text()
            assert isinstance(snapshot, str)
            for line in snapshot.splitlines():
                assert line.startswith("line-"), f"torn snapshot line: {line!r}"
    finally:
        stop.set()
        drain.join(timeout=_RELEASE_READER_S)

    assert drain.text().splitlines(), "the reader produced lines before EOF"


class _LockGuardedBuffer:
    """Iterable that raises like a concurrently-mutated ``deque``.

    ``deque`` raises ``RuntimeError: deque mutated during iteration`` when it is
    iterated while another thread mutates it. The pre-AR8.2 ``text()`` iterated
    without the buffer lock, so this raises; the fixed snapshot holds the lock
    across ``"".join(...)`` and returns the lines.
    """

    def __init__(self, lock: threading.Lock | None, lines: list[str]) -> None:
        self._lock = lock
        self._lines = lines

    def __iter__(self) -> Iterator[str]:
        if self._lock is None or not self._lock.locked():
            raise RuntimeError("deque mutated during iteration")
        return iter(self._lines)


def test_text_snapshot_is_taken_under_the_buffer_lock() -> None:
    """The deterministic half of the AR8.3(a) pin.

    A real drain handle's buffer is swapped for one that only tolerates
    iteration while the drain's own lock is held. Pre-fix (bare
    ``"".join(self._lines)``, no ``_lock``) the iteration is unsynchronised and
    raises ``RuntimeError``; the fixed ``text()`` snapshots under the lock.
    """

    stop = threading.Event()
    drain = _drain_helper()(_StayOpenStream(stop))
    try:
        lock = getattr(drain, "_lock", None)
        drain._lines = _LockGuardedBuffer(lock, ["alpha\n", "beta\n"])

        assert drain.text() == "alpha\nbeta\n"
    finally:
        stop.set()
        drain.join(timeout=_RELEASE_READER_S)
