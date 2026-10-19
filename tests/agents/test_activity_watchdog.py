"""Idle watchdog — diagnostic shape and driver-level stall detection."""

from __future__ import annotations

import io
import threading
import time
from typing import Any

from mergecraft.agents import codex as codex_module
from mergecraft.agents._stream_consumer import StreamSpanAccumulator
from mergecraft.agents.activity_watchdog import AgentDiagnostic, IdleWatchdog
from mergecraft.agents.shared import AgentRunContext
from mergecraft.mcp.context import PayloadEvent, ResolvedPayload
from mergecraft.mcp.tool_state import init_tool_state


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_quiet_stream_stalls_and_reports_the_idle_span() -> None:
    clock = _Clock()
    killed: list[int | None] = []
    watchdog = IdleWatchdog(
        label="codex",
        interval_s=30.0,
        clock=clock,
        kill=lambda pid: killed.append(pid),
        process=type("P", (), {"pid": 4242})(),
    )
    watchdog.touch()

    clock.advance(29.0)
    assert watchdog.check() is False

    clock.advance(2.0)
    assert watchdog.check() is True
    diagnostic = watchdog.diagnostic()

    assert diagnostic.idle_seconds == 31.0
    assert diagnostic.event_count == 1
    assert "No model event arrived for 31s" in diagnostic.render()
    assert killed == []


def test_slow_but_streaming_run_does_not_trip() -> None:
    clock = _Clock()
    watchdog = IdleWatchdog(label="claude", interval_s=30.0, clock=clock)

    for _ in range(12):
        watchdog.touch()
        clock.advance(10.0)
        assert watchdog.check() is False


def test_diagnostic_names_provider_error_and_stderr_tail() -> None:
    accumulator = StreamSpanAccumulator(agent_name="opencode")
    accumulator.set_stream_error("provider billing exhausted")
    watchdog = IdleWatchdog(
        label="opencode",
        interval_s=0,
        accumulator=accumulator,
        stderr_text=lambda: "line one\nline two\n",
    )
    watchdog.touch()

    diagnostic = watchdog.diagnostic()

    assert "provider billing exhausted" in diagnostic.render()
    assert "line two" in diagnostic.render()
    assert diagnostic.as_metadata()["idle_timeout"] is True


def test_diagnostic_redacts_provider_errors_and_stderr_before_publication() -> None:
    diagnostic = AgentDiagnostic(
        label="opencode",
        event_count=0,
        idle_seconds=10.0,
        saw_model_output=False,
        last_provider_error="Incorrect API key provided: sk-abcdefghijklmnopqrstuvwxyz123456",
        stderr_tail=("Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz0123456789",),
    )

    rendered = diagnostic.render()
    metadata = diagnostic.as_metadata()

    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in rendered
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in rendered
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in str(metadata)


def test_diagnostic_redacts_before_it_truncates_the_stderr_tail() -> None:
    secret = "Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    padded = ("x" * 2990) + secret + ("y" * 100)
    watchdog = IdleWatchdog(
        label="codex",
        interval_s=0,
        stderr_text=lambda: padded,
    )

    rendered = watchdog.diagnostic().render()

    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in rendered
    assert "ghp_abcdef" not in rendered


def test_metadata_and_render_are_advisory_not_a_verdict() -> None:
    diagnostic = AgentDiagnostic(
        label="codex",
        event_count=0,
        idle_seconds=900.0,
        saw_model_output=False,
    )

    rendered = diagnostic.render()

    assert "produced no output at all" in rendered
    assert "failed" not in rendered.casefold()


class _StallingStream:
    """A stdout stream that blocks until the watchdog kills the process."""

    def __init__(self, stop: threading.Event) -> None:
        self._stop = stop

    def __iter__(self) -> _StallingStream:
        return self

    def __next__(self) -> str:
        self._stop.wait(5.0)
        raise StopIteration


class _StreamingStream:
    """A stdout stream that keeps emitting events faster than the interval."""

    def __init__(self, count: int = 8, delay: float = 0.01) -> None:
        self._count = count
        self._delay = delay
        self._index = 0

    def __iter__(self) -> _StreamingStream:
        return self

    def __next__(self) -> str:
        if self._index >= self._count:
            raise StopIteration
        self._index += 1
        time.sleep(self._delay)
        return '{"type":"message.completed","text":"working"}\n'


class _FakeProcess:
    def __init__(self, stdout: Any, pid: int = 4242) -> None:
        self.stdout = stdout
        self.stderr = io.StringIO("last stderr line\n")
        self.pid = pid

    def wait(self, timeout: float | None = None) -> int:
        return 0


def _ctx() -> AgentRunContext:
    state = init_tool_state(owner="acme", name="demo", dir="/work")
    return AgentRunContext(
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        mcp_server_url="",
        tmpdir="/tmp",
        subagent_denied_tools=(),
        instructions=type("I", (), {"system": "", "user": "review"})(),
        tool_state=state,
        idle_timeout_s=0.05,
    )


def test_codex_driver_fails_fast_when_the_stream_goes_quiet(monkeypatch: Any) -> None:
    stop = threading.Event()
    killed: list[int | None] = []

    def _kill(pid: int | None, *, grace_s: float = 0.2) -> None:
        killed.append(pid)
        stop.set()

    monkeypatch.setattr("mergecraft.utils.process_group.kill_process_group", _kill)
    monkeypatch.setattr(
        codex_module,
        "spawn_agent_cli",
        lambda *args, **kwargs: _FakeProcess(_StallingStream(stop)),
    )

    result = codex_module._run_codex_streaming(
        cmd=["codex", "exec"],
        ctx=_ctx(),
        model=None,
        prompt="review",
    )

    assert result.success is False
    assert result.metadata.get("idle_timeout") is True
    assert "No model event arrived" in (result.error or "")
    assert killed == [4242]


def test_codex_driver_survives_a_slow_but_streaming_run(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        codex_module,
        "spawn_agent_cli",
        lambda *args, **kwargs: _FakeProcess(_StreamingStream()),
    )

    result = codex_module._run_codex_streaming(
        cmd=["codex", "exec"],
        ctx=_ctx(),
        model=None,
        prompt="review",
    )

    assert result.success is True
    assert "idle_timeout" not in result.metadata
