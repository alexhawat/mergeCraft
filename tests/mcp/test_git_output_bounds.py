"""Git output must be bounded before returning or caching a partial blob."""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.mcp.test_git_tool import _ctx
from tests.support.policy_fixtures import commit_all, init_git_repo

from mergecraft.mcp import git as git_mod


async def test_git_refuses_oversized_blob_without_caching_partial_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def prepare() -> None:
        init_git_repo(tmp_path)
        (tmp_path / "large.txt").write_text("safe text\n" * 2000)
        commit_all(tmp_path, "large blob")

    await asyncio.to_thread(prepare)
    monkeypatch.setattr(git_mod, "MAX_GIT_OUTPUT_BYTES", 4096, raising=False)
    ctx = _ctx(tmp_path)
    result = await git_mod.git_tool(ctx).execute({"command": "show", "args": ["HEAD:large.txt"]})
    assert result.is_error
    assert "output" in result.content[0]["text"].lower()
    assert "exceed" in result.content[0]["text"].lower()
    assert ctx.tool_state.git_show_cache == {}


@pytest.mark.parametrize("stream", ["stdout", "stderr"], ids=["stdout", "stderr"])
async def test_git_output_overflow_stops_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stream: str
) -> None:
    import sys

    bindir = tmp_path / "bin"
    bindir.mkdir()
    started, finished = tmp_path / "started", tmp_path / "finished"
    wrapper = bindir / "git"
    wrapper.write_text(
        f"#!{sys.executable}\nimport os,sys,time\nfrom pathlib import Path\n"
        f"Path({str(started)!r}).write_text(str(os.getpid()))\n"
        f"sys.{stream}.write('x' * 65536)\nsys.{stream}.flush()\n"
        f"time.sleep(1)\nPath({str(finished)!r}).write_text('late')\n"
    )
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(git_mod, "MAX_GIT_OUTPUT_BYTES", 4096)
    with pytest.raises(RuntimeError, match="output exceeded"):
        await asyncio.to_thread(git_mod._run_git, ["status"], cwd=str(tmp_path))
    assert not finished.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int(started.read_text()), 0)


async def test_git_tool_bounds_reaping_and_closes_pipes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate a child the OS cannot reap after output overflow."""
    from mergecraft.utils import git_process
    from mergecraft.utils.process_group import active_process_groups

    class UnreapableChild:
        def __init__(self) -> None:
            read_fd, write_fd = os.pipe()
            with os.fdopen(write_fd, "wb") as writer:
                writer.write(b"oversized")
            self.stdout = os.fdopen(read_fd, "rb")
            error_fd, unused_fd = os.pipe()
            os.close(unused_fd)
            self.stderr = os.fdopen(error_fd, "rb")
            self.stdin = None
            self.pid = os.getpid()
            self.waits: list[float | None] = []

        def __enter__(self) -> UnreapableChild:
            return self

        def __exit__(self, *_exc: object) -> None:
            self.stdout.close()
            self.stderr.close()
            self.wait()

        def wait(self, timeout: float | None = None) -> int:
            self.waits.append(timeout)
            if timeout is None:
                raise AssertionError("Popen.__exit__ made an unbounded wait")
            raise subprocess.TimeoutExpired("git", timeout)

    ctx = _ctx(tmp_path)
    child = UnreapableChild()
    kills: list[int] = []

    def kill(pid: int) -> None:
        assert pid in active_process_groups()
        kills.append(pid)

    monkeypatch.setattr(git_process.subprocess, "Popen", lambda *_a, **_kw: child)
    monkeypatch.setattr(git_process, "kill_process_group", kill)
    monkeypatch.setattr(git_mod, "MAX_GIT_OUTPUT_BYTES", 1)
    try:
        result = await git_mod.git_tool(ctx).execute({"command": "status"})
        assert result.is_error
        assert "output exceeded" in result.content[0]["text"]
        assert child.waits == [5]
        assert kills == [child.pid]
        assert child.pid not in active_process_groups()
        assert child.stdout.closed
        assert child.stderr.closed
    finally:
        child.stdout.close()
        child.stderr.close()


async def test_git_tool_closes_pipes_on_success_and_cached_show(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init_git_repo(tmp_path)
    (tmp_path / "file.txt").write_text("content\n")
    commit_all(tmp_path, "blob")
    ctx = _ctx(tmp_path)
    original = subprocess.Popen
    children: list[tuple[list[str], subprocess.Popen[bytes]]] = []

    def spawn(argv: list[str], *args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        child = original(argv, *args, **kwargs)
        if kwargs.get("start_new_session"):
            children.append((argv, child))
        return child

    monkeypatch.setattr(subprocess, "Popen", spawn)
    tool = git_mod.git_tool(ctx)
    result = await tool.execute({"command": "status"})
    assert not result.is_error, result.content
    for _ in range(2):
        result = await tool.execute({"command": "show", "args": ["HEAD:file.txt"]})
        assert not result.is_error, result.content
        assert "content" in result.content[0]["text"]
    assert len([argv for argv, _ in children if "show" in argv]) == 1
    assert len([argv for argv, _ in children if "cat-file" in argv]) == 2
    assert all(
        child.returncode == 0
        and child.stdout is not None
        and child.stdout.closed
        and child.stderr is not None
        and child.stderr.closed
        and (child.stdin is None or child.stdin.closed)
        for _, child in children
    )
