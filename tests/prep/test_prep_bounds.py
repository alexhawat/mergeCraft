"""Dependency prep is bounded, supervised, waitable from the MCP loop, and agent-safe.

Contracts (#1331):

- The agent can wait for an install that the orchestrator started on the main
  loop: ``await_dependency_installation`` runs on the MCP server's own loop.
- A hung install is stopped at the prep deadline and its whole process group
  (leader and grandchildren) is killed; the step is recorded as a failed install.
- Publication waits a bounded time for a still-running install, then stops it
  and reports why, instead of holding the publish stage.
- Prep never restores tracked files in a checkout the agent is editing.

Every case drives the real prep code (``run_prep_phase``, the real Node step,
``start_installation``) against a fake ``npm`` on ``PATH``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import stat
import subprocess
import threading
import time
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.main import _prep_failure_reason
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.dependencies import await_dependency_installation_tool, start_installation
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.prep import PrepOptions, PrepRun, run_prep_phase
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.process_group import active_process_groups

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_QUICK_NPM = "#!/bin/sh\nsleep 0.3\necho installed\n"
_HUNG_NPM = (
    "#!/bin/sh\n"
    'echo $$ > "$PREP_TEST_DIR/leader.pid"\n'
    "sleep 30 &\n"
    'echo $! > "$PREP_TEST_DIR/child.pid"\n'
    "wait\n"
)
_EDITING_NPM = '#!/bin/sh\necho "agent edit" > app.js\n'


def _node_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(json.dumps({"name": "fixture"}) + "\n", encoding="utf-8")
    (repo / "package-lock.json").write_text("{}\n", encoding="utf-8")
    return repo


@pytest.fixture
def fake_npm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Install a scripted ``npm`` first on ``PATH``; kill anything it left behind."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("PREP_TEST_DIR", str(tmp_path))

    def _install(script: str) -> None:
        npm = bin_dir / "npm"
        npm.write_text(script, encoding="utf-8")
        npm.chmod(npm.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    yield _install
    for name in ("leader.pid", "child.pid"):
        pid_file = tmp_path / name
        if pid_file.is_file():
            with contextlib.suppress(ProcessLookupError, PermissionError, ValueError):
                os.kill(int(pid_file.read_text().strip()), signal.SIGKILL)


def _tool_ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="unknown"), shell="restricted"),
        github=GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier="trusted",
    )


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_until_dead(pid: int, *, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.05)
    return not _pid_alive(pid)


async def _wait_until_dead_async(pid: int, *, timeout_s: float) -> bool:
    """Poll without blocking the loop, so a scheduled cancellation can run."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        await asyncio.sleep(0.05)
    return not _pid_alive(pid)


def _read_pid(path: Path) -> int | None:
    text = path.read_text().strip() if path.is_file() else ""
    return int(text) if text else None


async def _wait_for_file(path: Path, *, timeout_s: float = 5.0) -> int:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        pid = _read_pid(path)
        if pid is not None:
            return pid
        await asyncio.sleep(0.02)
    msg = f"fake npm never wrote {path.name}"
    raise AssertionError(msg)


async def test_agent_waits_for_install_started_on_another_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_npm: Any
) -> None:
    """``await_dependency_installation`` on the MCP loop waits for the main loop's install."""
    fake_npm(_QUICK_NPM)
    monkeypatch.chdir(_node_repo(tmp_path))
    ctx = _tool_ctx(tmp_path)
    start_installation(ctx)  # the orchestrator starts prep on its own (this) loop
    state = ctx.tool_state.dependency_installation
    assert state is not None
    assert state.status == "in_progress"
    assert isinstance(state.promise, PrepRun)

    mcp_loop = asyncio.new_event_loop()
    thread = threading.Thread(target=mcp_loop.run_forever, name="mcp-loop", daemon=True)
    thread.start()
    try:
        tool = await_dependency_installation_tool(ctx)
        call = asyncio.run_coroutine_threadsafe(tool.execute({}), mcp_loop)
        response = await asyncio.wait_for(asyncio.wrap_future(call), timeout=20)
    finally:
        mcp_loop.call_soon_threadsafe(mcp_loop.stop)
        thread.join(timeout=5)
        mcp_loop.close()

    text = " ".join(item.get("text", "") for item in response.content)
    assert response.is_error is False, text
    assert "Node.js dependencies installed successfully via npm" in text
    assert state.status == "completed"


async def test_hung_install_is_killed_at_the_prep_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_npm: Any
) -> None:
    """A hung ``npm ci`` is stopped at the deadline with its whole process group."""
    fake_npm(_HUNG_NPM)
    monkeypatch.chdir(_node_repo(tmp_path))

    started = time.monotonic()
    results = await run_prep_phase(PrepOptions(timeout_s=0.5, agent_owned_tree=True))
    elapsed = time.monotonic() - started

    assert elapsed < 10.0, f"prep took {elapsed:.1f}s past a 0.5s deadline"
    [node] = results
    assert node.language == "node"
    assert node.dependencies_installed is False
    assert "timed out after 0.5s" in node.issues[0]
    leader = int((tmp_path / "leader.pid").read_text().strip())
    child = int((tmp_path / "child.pid").read_text().strip())
    assert _wait_until_dead(leader, timeout_s=3.0), "the install's session leader survived"
    assert _wait_until_dead(child, timeout_s=3.0), "the install's grandchild survived"
    assert leader not in active_process_groups()


async def test_install_registers_its_process_group_while_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_npm: Any
) -> None:
    """A running install is in the registry the run's timeout handler kills."""
    fake_npm(_HUNG_NPM)
    monkeypatch.chdir(_node_repo(tmp_path))
    task = asyncio.ensure_future(run_prep_phase(PrepOptions(timeout_s=10, agent_owned_tree=True)))
    try:
        leader = await _wait_for_file(tmp_path / "leader.pid")
        assert leader in active_process_groups()
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    assert _wait_until_dead(leader, timeout_s=3.0)
    assert leader not in active_process_groups()


async def test_publication_stops_an_install_still_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_npm: Any
) -> None:
    """``_prep_failure_reason`` waits a bounded time, then stops the install and says so."""
    fake_npm(_HUNG_NPM)
    monkeypatch.chdir(_node_repo(tmp_path))
    ctx = _tool_ctx(tmp_path)
    start_installation(ctx)
    leader = await _wait_for_file(tmp_path / "leader.pid")

    started = time.monotonic()
    reason = await _prep_failure_reason(ctx, wait_s=0.2)

    assert time.monotonic() - started < 5.0
    assert reason is not None
    assert "still running" in reason
    assert await _wait_until_dead_async(leader, timeout_s=5.0), "the stopped install kept running"
    state = ctx.tool_state.dependency_installation
    assert state is not None
    for _ in range(100):
        if state.status != "in_progress":
            break
        await asyncio.sleep(0.02)
    assert state.status == "failed"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _git_repo_with_tracked_file(tmp_path: Path) -> Path:
    repo = _node_repo(tmp_path)
    (repo / "app.js").write_text("original\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


async def test_prep_keeps_edits_in_a_checkout_the_agent_shares(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_npm: Any
) -> None:
    """A tracked file that changed while prep ran is left alone on an agent-owned tree."""
    fake_npm(_EDITING_NPM)
    repo = _git_repo_with_tracked_file(tmp_path)
    monkeypatch.chdir(repo)

    await run_prep_phase(PrepOptions(agent_owned_tree=True))

    assert (repo / "app.js").read_text(encoding="utf-8") == "agent edit\n"


async def test_prep_alone_still_restores_files_it_dirtied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_npm: Any
) -> None:
    """Control: with no agent sharing the checkout, prep restores what it changed."""
    fake_npm(_EDITING_NPM)
    repo = _git_repo_with_tracked_file(tmp_path)
    monkeypatch.chdir(repo)

    await run_prep_phase(PrepOptions(agent_owned_tree=False))

    assert (repo / "app.js").read_text(encoding="utf-8") == "original\n"


async def test_run_started_install_treats_the_checkout_as_agent_owned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``start_installation`` (the run's and the agent's entry point) never restores files."""
    captured: list[PrepOptions] = []

    async def _fake_prep(options: PrepOptions | None = None) -> list[Any]:
        assert options is not None
        captured.append(options)
        return []

    monkeypatch.setattr("mergecraft.mcp.dependencies.run_prep_phase", _fake_prep)
    ctx = _tool_ctx(tmp_path)
    start_installation(ctx)
    state = ctx.tool_state.dependency_installation
    assert state is not None
    await state.promise
    assert [options.agent_owned_tree for options in captured] == [True]
