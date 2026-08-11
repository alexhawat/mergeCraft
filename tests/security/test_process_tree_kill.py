"""Plan W9.1/W9.2 — process-group isolation and tree kill on timeout (``#14``).

Contracts:

- W9.1: every agent CLI spawn uses ``start_new_session=True`` so the agent
  process heads its own process group.
- W9.2: the timeout path kills the whole group (TERM → grace → KILL, mirroring
  ``mcp/shell.py``), so a CLI double that forks a child leaves **no orphan**.

The functional test drives the real ``claude`` streaming runner against a
stub CLI on ``PATH`` — no mocks in the kill path.
"""

from __future__ import annotations

import ast
import contextlib
import os
import signal
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENT_MODULES = ["claude.py", "codex.py", "gemini.py", "opencode.py"]


def _popen_calls_without_new_session(source: str) -> list[int]:
    tree = ast.parse(source)
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_popen = (isinstance(func, ast.Attribute) and func.attr == "Popen") or (
            isinstance(func, ast.Name) and func.id == "Popen"
        )
        if not is_popen:
            continue
        if not any(kw.arg == "start_new_session" for kw in node.keywords):
            lines.append(node.lineno)
    return lines


@pytest.mark.parametrize("module_name", _AGENT_MODULES)
def test_agent_spawns_use_process_groups(module_name: str) -> None:
    """W9.1 — every ``subprocess.Popen`` in agent code heads its own group.

    Fails if the guard is deleted: removing ``start_new_session=True`` makes
    the kill-group call unable to reach grandchildren and this goes red.
    """
    source_path = _REPO_ROOT / "src" / "mergecraft" / "agents" / module_name
    lines = _popen_calls_without_new_session(source_path.read_text(encoding="utf-8"))
    assert not lines, f"{module_name}: Popen call(s) at lines {lines} lack start_new_session=True"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="process groups are POSIX-only")
def test_timeout_kills_grandchildren(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """W9.2 — a CLI double that forks a child must not orphan it on timeout.

    The double closes its own stdio (so the stream consumer returns) and then
    sleeps with a ``sleep`` child behind it. Today's ``process.kill()`` only
    reaches the direct child; the contract requires the whole group to die.
    """
    from mergecraft.agents.claude import _run_claude_once
    from mergecraft.mcp.tool_state import init_tool_state

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pid_file = tmp_path / "grandchild.pid"
    cli = bin_dir / "claude"
    # The background child must NOT inherit the pipe fds — otherwise the
    # parent's stream consumer blocks on it and the test measures the sleep
    # instead of the kill. The double closes its own stdio so the parent sees
    # EOF immediately, then idles behind a long-lived grandchild.
    cli.write_text(
        "#!/bin/bash\n"
        "sleep 300 </dev/null >/dev/null 2>&1 &\n"
        f"echo $! > {pid_file}\n"
        "exec 1>&- 2>&-\n"
        "sleep 300\n",
        encoding="utf-8",
    )
    cli.chmod(0o755)

    from mergecraft.agents.shared import AgentRunContext

    ctx = AgentRunContext(
        payload={"shell": "restricted"},
        mcp_server_url="",
        tmpdir=str(tmp_path),
        subagent_denied_tools=(),
        instructions=type("I", (), {"system": "", "user": "hi"})(),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
    )
    mcp_config = tmp_path / "mcp.json"
    mcp_config.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("MERGECRAFT_AGENT_TIMEOUT", "1")

    result = _run_claude_once(cli=str(cli), prompt="hi", ctx=ctx, mcp_config=str(mcp_config))
    assert not result.success, "double CLI should have timed out"

    assert pid_file.exists(), "double CLI never wrote its grandchild pid"
    grandchild = int(pid_file.read_text().strip())
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and _pid_alive(grandchild):
            time.sleep(0.05)
        assert not _pid_alive(grandchild), (
            f"grandchild pid {grandchild} survived the timeout kill — process tree leaked"
        )
    finally:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(grandchild, signal.SIGKILL)


def test_mcp_shell_kill_pg_is_group_based() -> None:
    """Baseline — the reference implementation kills by process group (pinned)."""
    source = (_REPO_ROOT / "src" / "mergecraft" / "mcp" / "shell.py").read_text(encoding="utf-8")
    assert "os.killpg" in source, "mcp/shell.py lost its group kill — the W9 mirror target"


# ── Direct symbol coverage for utils.process_group (W9 deliverables) ──────────


@pytest.fixture(autouse=True)
def _clear_active_process_groups() -> None:
    """Isolate registry mutations across direct-symbol tests."""
    from mergecraft.utils.process_group import active_process_groups, unregister_process_group

    for pid in active_process_groups():
        unregister_process_group(pid)
    yield
    for pid in active_process_groups():
        unregister_process_group(pid)


def test_register_process_group_tracks_pid() -> None:
    """Direct ``register_process_group`` — None is a no-op; int joins the set."""
    from mergecraft.utils.process_group import (
        active_process_groups,
        register_process_group,
        unregister_process_group,
    )

    register_process_group(None)
    assert active_process_groups() == frozenset()

    register_process_group(424242)
    assert 424242 in active_process_groups()
    unregister_process_group(424242)
    assert 424242 not in active_process_groups()


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="process groups are POSIX-only")
def test_kill_process_group_reaps_session_leader() -> None:
    """Direct ``kill_process_group`` — TERM→grace→KILL reaches the session leader.

    Fails if the helper is deleted or falls back to a no-op: the child survives.
    """
    import subprocess

    from mergecraft.utils.process_group import kill_process_group

    proc = subprocess.Popen(
        ["sleep", "300"],
        start_new_session=True,
    )
    try:
        kill_process_group(proc.pid, grace_s=0.05)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=2)
        assert proc.poll() is not None, f"pid {proc.pid} survived kill_process_group"
        assert not _pid_alive(proc.pid), f"pid {proc.pid} still in the process table"
    finally:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(proc.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=1)


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="process groups are POSIX-only")
def test_wait_or_kill_process_group_times_out_and_kills() -> None:
    """Direct ``wait_or_kill_process_group`` — TimeoutExpired + group reap.

    Fails if the timeout path only waits (no kill): the sleep child stays alive.
    """
    import subprocess

    from mergecraft.utils.process_group import wait_or_kill_process_group

    proc = subprocess.Popen(
        ["sleep", "300"],
        start_new_session=True,
    )
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            wait_or_kill_process_group(proc, timeout=0.2)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and _pid_alive(proc.pid):
            time.sleep(0.05)
        assert not _pid_alive(proc.pid), (
            f"pid {proc.pid} survived wait_or_kill_process_group timeout"
        )
    finally:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(proc.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=1)


def test_track_process_group_registers_for_block_lifetime() -> None:
    """Direct ``track_process_group`` — pid registered inside ``with``, cleared after."""
    from types import SimpleNamespace

    from mergecraft.utils.process_group import active_process_groups, track_process_group

    fake = SimpleNamespace(pid=777001)
    assert 777001 not in active_process_groups()
    with track_process_group(fake):  # type: ignore[arg-type]
        assert 777001 in active_process_groups()
    assert 777001 not in active_process_groups()


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="process groups are POSIX-only")
def test_kill_all_active_process_groups_reaps_registered() -> None:
    """Direct ``kill_all_active_process_groups`` — every registered session dies.

    Guard-deletion anchor: if the outer ``main`` timeout stopped calling this,
    registered agent trees would leak; this pins the helper itself.
    """
    import subprocess

    from mergecraft.utils.process_group import (
        kill_all_active_process_groups,
        register_process_group,
    )

    proc = subprocess.Popen(
        ["sleep", "300"],
        start_new_session=True,
    )
    register_process_group(proc.pid)
    try:
        kill_all_active_process_groups(grace_s=0.05)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=2)
        assert proc.poll() is not None, f"pid {proc.pid} survived kill_all_active_process_groups"
        assert not _pid_alive(proc.pid), f"pid {proc.pid} still in the process table"
    finally:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(proc.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=1)
