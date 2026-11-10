"""The ``repo`` argument of the read-only ``git`` tool is honoured, never ignored (#1258)."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest
from tests.mcp.test_git_tool import _ctx
from tests.support.policy_fixtures import commit_all, init_git_repo

from mergecraft.mcp.git import (
    commit_changes_tool,
    delete_branch_tool,
    git_fetch_tool,
    git_tool,
    push_branch_tool,
    push_tags_tool,
)
from mergecraft.mcp.tool_state import ensure_repo_state

if TYPE_CHECKING:
    from pathlib import Path


def _repo(path: Path, content: str) -> None:
    path.mkdir()
    init_git_repo(path)
    (path / "README.md").write_text(content)
    commit_all(path, "initial")


async def _two_repo_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    primary, other = tmp_path / "primary", tmp_path / "other"
    await asyncio.to_thread(_repo, primary, "primary\n")
    await asyncio.to_thread(_repo, other, "other\n")
    ctx = _ctx(tmp_path)
    ctx.tool_state.repos["acme/demo"].dir = str(primary)
    ensure_repo_state(ctx.tool_state, owner="acme", name="other", dir=str(other), access="read")
    return git_tool(ctx)


async def _show_readme(tool: Any, repo: str | None) -> Any:
    params: dict[str, Any] = {"command": "show", "args": ["HEAD:README.md"]}
    if repo is not None:
        params["repo"] = repo
    return await tool.execute(params)


async def _text(result: Any) -> str:
    assert not result.is_error, result.content
    payload = json.loads(result.content[0]["text"])
    return str(payload["output"])


async def test_repo_selects_registered_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = await _two_repo_tool(tmp_path, monkeypatch)
    assert "primary" in await _text(await _show_readme(tool, None))
    assert "other" in await _text(await _show_readme(tool, "other"))
    assert "other" in await _text(await _show_readme(tool, "acme/other"))
    assert "primary" in await _text(await _show_readme(tool, "acme/demo"))


async def test_unknown_repo_is_an_error_not_a_primary_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = await _two_repo_tool(tmp_path, monkeypatch)
    result = await _show_readme(tool, "nope")
    assert result.is_error is True
    assert "not a registered checkout" in result.content[0]["text"]


async def test_non_string_repo_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = await _two_repo_tool(tmp_path, monkeypatch)
    result = await tool.execute({"command": "status", "repo": 7})
    assert result.is_error is True


@pytest.mark.parametrize(
    "factory",
    [
        git_fetch_tool,
        push_branch_tool,
        push_tags_tool,
        delete_branch_tool,
        commit_changes_tool,
    ],
)
def test_tools_that_always_act_on_the_primary_checkout_do_not_advertise_repo(
    tmp_path: Path, factory: Any
) -> None:
    schema = factory(_ctx(tmp_path)).input_schema
    assert "repo" not in schema["properties"]


def test_git_tool_advertises_repo(tmp_path: Path) -> None:
    assert "repo" in git_tool(_ctx(tmp_path)).input_schema["properties"]
