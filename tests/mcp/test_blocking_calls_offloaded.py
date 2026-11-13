"""Blocking subprocess work in MCP handlers must not stall the event loop."""

from __future__ import annotations

import asyncio
import subprocess
import threading
import time
from typing import TYPE_CHECKING, Any

from tests.mcp.test_shell_git_guard import _ctx
from tests.support.tool_context import inner_mutation_guard_probe

from mergecraft.mcp import git as git_mod
from mergecraft.mcp import shell as shell_mod
from mergecraft.mcp.git import git_tool
from mergecraft.mcp.shell import shell_tool

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


async def _ticks_while(work: Any) -> tuple[Any, int]:
    """Run ``work`` while counting 20ms loop ticks; a blocked loop counts ~0."""
    ticks = 0
    stop = asyncio.Event()

    async def ticker() -> None:
        nonlocal ticks
        while not stop.is_set():
            await asyncio.sleep(0.02)
            ticks += 1

    task = asyncio.create_task(ticker())
    try:
        result = await work
    finally:
        stop.set()
        await task
    return result, ticks


async def test_shell_foreground_command_does_not_block_the_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def spawn(command: str, *, env: dict[str, str], cwd: str, stdout: Any, stderr: Any, **_: Any):
        return subprocess.Popen(
            ["bash", "-c", command],
            cwd=cwd,
            env=env,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )

    monkeypatch.setattr(shell_mod, "_spawn_shell", spawn)
    spec = shell_tool(_ctx(tmp_path, shell="enabled"))
    with inner_mutation_guard_probe():
        result, ticks = await _ticks_while(
            spec.execute({"command": "sleep 1; echo done", "description": "slow"})
        )
    assert not result.is_error, result.content[0]["text"]
    assert "done" in result.content[0]["text"]
    assert ticks >= 10, f"event loop was blocked (only {ticks} ticks in a 1s command)"


async def test_git_handler_runs_the_blocking_call_off_the_loop_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[int] = []

    def slow_git(args: list[str], *, cwd: str) -> str:
        seen.append(threading.get_ident())
        time.sleep(0.5)
        return "ok"

    monkeypatch.setattr(git_mod, "_run_git", slow_git)
    spec = git_tool(_ctx(tmp_path, shell="enabled"))
    result, ticks = await _ticks_while(spec.execute({"command": "status"}))
    assert not result.is_error, result.content[0]["text"]
    assert seen
    assert seen[0] != threading.get_ident()
    assert ticks >= 10, f"event loop was blocked (only {ticks} ticks)"


def test_second_timeout_after_kill_is_contained_and_reaped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A descendant holding the pipes open must not leak TimeoutExpired / a zombie."""
    calls: dict[str, int] = {"communicate": 0, "kill": 0, "wait": 0}

    class _Stuck:
        pid = 0
        returncode: int | None = None

        def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
            calls["communicate"] += 1
            raise subprocess.TimeoutExpired("sh", timeout or 0, output=b"partial", stderr=b"")

        def kill(self) -> None:
            calls["kill"] += 1

        def wait(self, timeout: float | None = None) -> int:
            calls["wait"] += 1
            self.returncode = -9
            return -9

    monkeypatch.setattr(shell_mod, "_spawn_shell", lambda *a, **k: _Stuck())
    monkeypatch.setattr(shell_mod, "kill_process_group", lambda pid: None)

    stdout_b, _stderr_b, returncode, timed_out = shell_mod._run_foreground(
        "sleep 99", env={}, cwd="/tmp", timeout_s=0.01, isolate_network=False
    )
    assert timed_out is True
    assert stdout_b == b"partial"
    assert returncode == -9
    assert calls == {"communicate": 2, "kill": 1, "wait": 1}
