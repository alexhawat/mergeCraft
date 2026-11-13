"""Blocking subprocess work in MCP handlers must not stall the event loop."""

from __future__ import annotations

import asyncio
import subprocess
import threading
import time
from io import BytesIO
from typing import TYPE_CHECKING, Any

import pytest
from tests.mcp.test_shell_git_guard import _ctx
from tests.support.tool_context import write_capable_mcp_mode

from mergecraft.mcp import git as git_mod
from mergecraft.mcp import shell as shell_mod
from mergecraft.mcp.git import git_tool
from mergecraft.mcp.shell import shell_tool

if TYPE_CHECKING:
    from pathlib import Path


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
    with write_capable_mcp_mode():
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
        stdin = stdout = stderr = None
        returncode: int | None = None

        def __enter__(self):
            return self

        def __exit__(self, *args: Any) -> None:
            pass

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


async def test_rpc_deadline_reaps_foreground_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os
    import shlex
    import sys

    import pytest

    from mergecraft.mcp.rpc import dispatch_mcp_rpc

    monkeypatch.setenv("MERGECRAFT_ALLOW_UNSANDBOXED_SHELL", "1")
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "none")
    ctx = _ctx(tmp_path, shell="enabled")
    ctx.tool_state.selected_mode = "Fix"
    spec = shell_tool(ctx)
    spec.timeout_ms = 500
    script = tmp_path / "slow.py"
    script.write_text(
        "import os,time\nfrom pathlib import Path\n"
        "Path('started').write_text(str(os.getpid()))\n"
        "time.sleep(5)\nPath('finished').write_text('late')\n"
    )
    response = await dispatch_mcp_rpc(
        1,
        "tools/call",
        {
            "name": spec.name,
            "arguments": {
                "command": shlex.join([sys.executable, str(script)]),
                "description": "slow",
            },
        },
        tools=[spec],
        by_name={spec.name: spec},
        tool_ctx=ctx,
        validators={},
    )
    assert response["error"]["code"] == -32000
    assert not (tmp_path / "finished").exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int((tmp_path / "started").read_text()), 0)


@pytest.mark.parametrize("failure", ["timeout", "communication"])
async def test_foreground_cleanup_never_reintroduces_an_unbounded_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """RPC cleanup stays bounded even when the OS cannot reap a killed child."""
    from mergecraft.mcp.rpc import dispatch_mcp_rpc
    from mergecraft.utils.process_group import active_process_groups

    waits: list[float | None] = []
    killed_groups: list[int | None] = []
    kills: list[bool] = []

    class Unreapable(subprocess.Popen[bytes]):
        def __init__(self) -> None:
            self.pid = 4242
            self.returncode = None
            self.stdin = None
            self.stdout = BytesIO()
            self.stderr = BytesIO()

        def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
            if failure == "communication":
                raise OSError("communication failed")
            raise subprocess.TimeoutExpired("shell", timeout or 0, output=b"partial", stderr=b"")

        def kill(self) -> None:
            kills.append(True)

        def wait(self, timeout: float | None = None) -> int:
            waits.append(timeout)
            assert timeout is not None, "cleanup attempted an unbounded process wait"
            raise subprocess.TimeoutExpired("shell", timeout)

    process = Unreapable()
    groups_before = active_process_groups()
    monkeypatch.setattr(shell_mod, "_spawn_shell", lambda *a, **k: process)
    monkeypatch.setattr(shell_mod, "kill_process_group", killed_groups.append)
    ctx = _ctx(tmp_path, shell="enabled")
    ctx.tool_state.selected_mode = "Fix"
    spec = shell_tool(ctx)
    response = await dispatch_mcp_rpc(
        1,
        "tools/call",
        {
            "name": spec.name,
            "arguments": {"command": "probe", "description": "probe", "timeout": 1},
        },
        tools=[spec],
        by_name={spec.name: spec},
        tool_ctx=ctx,
        validators={},
    )
    assert waits, response
    assert all(timeout is not None for timeout in waits), response
    assert killed_groups
    assert all(pid == process.pid for pid in killed_groups)
    assert kills
    assert process.stdout.closed
    assert process.stderr.closed
    assert active_process_groups() == groups_before
    rendered = response["result"]
    if failure == "communication":
        assert rendered["isError"] is True
        assert "communication failed" in rendered["content"][0]["text"]
    else:
        assert rendered.get("isError") is not True, response
        assert "timed out" in rendered["content"][0]["text"]
