"""Cached file reads preserve repository, revision, and invocation identity."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest
from tests.mcp.test_git_tool import _ctx
from tests.support.policy_fixtures import commit_all, init_git_repo

from mergecraft.mcp.git import git_tool

if TYPE_CHECKING:
    from pathlib import Path


def _repo(path: Path, content: str) -> None:
    path.mkdir()
    init_git_repo(path)
    (path / "README.md").write_text(content)
    (path / "other.txt").write_text("other\n")
    commit_all(path, "initial")


async def _show(tool: Any, args: list[str]) -> dict[str, Any]:
    command = "show"
    if args[:1] == ["-C"]:
        command = "git"
        args = [*args[:2], "show", *args[2:]]
    result = await tool.execute({"command": command, "args": args})
    assert not result.is_error, result.content
    return json.loads(result.content[0]["text"])


@pytest.mark.parametrize("selector", ["-C", "--git-dir"])
async def test_show_cache_separates_authorized_repositories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selector: str
) -> None:
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    first, second = tmp_path / "first", tmp_path / "second"
    await asyncio.to_thread(_repo, first, "first\n")
    await asyncio.to_thread(_repo, second, "second\n")
    tool = git_tool(_ctx(tmp_path))

    def args(path: Path) -> list[str]:
        options = (
            ["-C", str(path)]
            if selector == "-C"
            else ["--git-dir", str(path / ".git"), "--work-tree", str(path)]
        )
        return [*options, "HEAD:README.md"]

    a = await _show(tool, args(first))
    b = await _show(tool, args(second))
    again = await _show(tool, args(first))

    assert a["output"] == "first"
    assert b["output"] == "second"
    assert a["outputPath"] != b["outputPath"]
    assert again.get("cached") is True


async def test_show_cache_resolves_moving_refs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    await asyncio.to_thread(_repo, repo, "before\n")
    ctx = _ctx(repo)
    ctx.tmpdir = str(tmp_path)
    tool = git_tool(ctx)
    first = await _show(tool, ["HEAD:README.md"])

    def advance() -> None:
        (repo / "README.md").write_text("after\n")
        commit_all(repo, "advance")

    await asyncio.to_thread(advance)
    second = await _show(tool, ["HEAD:README.md"])

    assert first["output"] == "before"
    assert second["output"] == "after"
    assert first["outputPath"] != second["outputPath"]


async def test_show_with_additional_operands_does_not_reuse_single_blob(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    await asyncio.to_thread(_repo, repo, "readme\n")
    ctx = _ctx(repo)
    ctx.tmpdir = str(tmp_path)
    tool = git_tool(ctx)
    first = await _show(tool, ["HEAD:README.md"])
    second = await _show(tool, ["HEAD:README.md", "HEAD:other.txt"])

    assert first["output"] == "readme"
    assert "other" in second["output"]
    assert first["outputPath"] != second["outputPath"]


async def test_show_reads_the_resolved_object_when_head_moves_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.mcp import git as git_module

    repo = tmp_path / "repo"
    await asyncio.to_thread(_repo, repo, "before\n")
    real_run = git_module._run_git
    moved = False

    def moving_run(args: list[str], **kwargs: Any) -> str:
        nonlocal moved
        output = real_run(args, **kwargs)
        if args[0] == "rev-parse" and not moved:
            moved = True
            (repo / "README.md").write_text("after\n")
            commit_all(repo, "advance")
        return output

    monkeypatch.setattr(git_module, "_run_git", moving_run)
    ctx = _ctx(repo)
    ctx.tmpdir = str(tmp_path)
    tool = git_tool(ctx)
    first = await _show(tool, ["HEAD:README.md"])
    second = await _show(tool, ["HEAD:README.md"])

    assert moved
    assert first["output"] == "before"
    assert second["output"] == "after"
