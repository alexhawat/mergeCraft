"""``MERGECRAFT_AGENT_TIMEOUT`` bounds a running, still-streaming agent (#1325).

The cap is a wall-clock deadline counted from spawn. A CLI that keeps emitting
events is never idle, so the idle watchdog cannot catch it; before this fix the
cap only started after stdout EOF and a busy child ran to completion.

The driver cases use a real child process in its own session, because the
defect is about when the process group is killed, which a stubbed stream
cannot show.
"""

from __future__ import annotations

import contextlib
import importlib
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from tests.agents.conftest import make_agent_run_context

from mergecraft.agents.activity_watchdog import WALL_CLOCK_TIMEOUT_KIND, IdleWatchdog

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

# The child streams one event every 0.1 s for about 5 s, then exits 0.
_BUSY_CHILD = """
import sys, time
for _ in range(50):
    sys.stdout.write('{"type": "heartbeat"}\\n')
    sys.stdout.flush()
    time.sleep(0.1)
sys.exit(0)
"""
_CAP_S = 1.0
# Well under the child's 5 s natural lifetime, with room for a slow CI host.
_RETURN_BOUND_S = 3.5


class _Clock:
    def __init__(self) -> None:
        self.now = 500.0

    def __call__(self) -> float:
        return self.now


def test_deadline_trips_even_while_events_keep_arriving() -> None:
    clock = _Clock()
    watchdog = IdleWatchdog(label="codex", interval_s=30.0, clock=clock, deadline_s=10.0)
    for _ in range(9):
        clock.now += 1.0
        watchdog.touch()
        assert watchdog.check() is False
    clock.now += 1.5
    watchdog.touch()

    assert watchdog.check() is True
    assert watchdog.deadline_hit is True
    diagnostic = watchdog.diagnostic()
    assert diagnostic.timeout_kind == WALL_CLOCK_TIMEOUT_KIND
    metadata = diagnostic.as_metadata()
    assert metadata["timeout"] is True
    assert metadata["cap_seconds"] == 10.0
    assert "idle_timeout" not in metadata
    assert "timed out" in diagnostic.render()


def test_deadline_runs_when_the_idle_watchdog_is_disabled() -> None:
    clock = _Clock()
    watchdog = IdleWatchdog(label="claude", interval_s=0.0, clock=clock, deadline_s=5.0)
    clock.now += 4.0
    assert watchdog.check() is False
    clock.now += 2.0
    assert watchdog.check() is True
    assert watchdog.deadline_hit is True


def test_idle_stall_still_reports_as_idle() -> None:
    clock = _Clock()
    watchdog = IdleWatchdog(label="gemini", interval_s=5.0, clock=clock, deadline_s=60.0)
    clock.now += 6.0
    assert watchdog.check() is True
    assert watchdog.deadline_hit is False
    assert watchdog.diagnostic().as_metadata()["idle_timeout"] is True


class _DriverSpec(NamedTuple):
    name: str
    module_name: str
    invoke: Callable[[Any, Any, Path], Any]


def _invoke_claude(module: Any, ctx: Any, tmp_path: Path) -> Any:
    return module._run_claude_once(
        cli="/usr/bin/claude",
        prompt="review this diff",
        ctx=ctx,
        mcp_config=str(tmp_path / "mcp.json"),
    )


def _invoke_codex(module: Any, ctx: Any, _tmp_path: Path) -> Any:
    return module._run_codex_streaming(
        cmd=["codex", "exec", "--json"], ctx=ctx, model="gpt-5.6-sol", prompt="review"
    )


def _invoke_gemini(module: Any, ctx: Any, _tmp_path: Path) -> Any:
    return module._run_gemini_streaming(
        cmd=["gemini", "-p"], ctx=ctx, model="gemini-3.1-pro", prompt="review"
    )


def _invoke_opencode(module: Any, ctx: Any, _tmp_path: Path) -> Any:
    return module._run_opencode_cli_streaming(
        cmd=["opencode", "run", "--format", "json"], ctx=ctx, env={}
    )


_DRIVERS = (
    _DriverSpec("claude", "mergecraft.agents.claude", _invoke_claude),
    _DriverSpec("codex", "mergecraft.agents.codex", _invoke_codex),
    _DriverSpec("gemini", "mergecraft.agents.gemini", _invoke_gemini),
    _DriverSpec("opencode", "mergecraft.agents.opencode", _invoke_opencode),
)


@pytest.fixture
def children() -> Iterator[list[subprocess.Popen[str]]]:
    spawned: list[subprocess.Popen[str]] = []
    yield spawned
    for proc in spawned:
        if proc.poll() is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()


@pytest.mark.parametrize("spec", _DRIVERS, ids=[spec.name for spec in _DRIVERS])
def test_driver_kills_a_streaming_agent_at_the_cap(
    spec: _DriverSpec,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    children: list[subprocess.Popen[str]],
) -> None:
    monkeypatch.setenv("MERGECRAFT_AGENT_TIMEOUT", str(_CAP_S))
    module = importlib.import_module(spec.module_name)
    ctx = make_agent_run_context(tmp_path, resolved_model="anthropic/claude-sonnet-5")

    def _spawn(*_args: object, **_kwargs: object) -> subprocess.Popen[str]:
        proc = subprocess.Popen(
            [sys.executable, "-c", _BUSY_CHILD],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        children.append(proc)
        return proc

    monkeypatch.setattr(module, "spawn_agent_cli", _spawn)
    if hasattr(module, "_build_env"):
        monkeypatch.setattr(module, "_build_env", lambda _ctx: {})

    started = time.monotonic()
    result = spec.invoke(module, ctx, tmp_path)
    elapsed = time.monotonic() - started

    assert elapsed < _RETURN_BOUND_S, f"{spec.name} ran {elapsed:.1f}s past a {_CAP_S}s cap"
    assert result.success is False
    assert result.metadata.get("timeout") is True
    assert "timed out" in (result.error or "")
    assert children[0].poll() is not None, "the capped child must be dead"
