"""Git output must be bounded before returning or caching a partial blob."""

from __future__ import annotations

import asyncio
from pathlib import Path

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
    import os
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
