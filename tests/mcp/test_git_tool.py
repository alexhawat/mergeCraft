"""Tests for git MCP tool input normalization (redundant subcommand tolerance)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.git import git_tool
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes


def _ctx(tmp_path: Path) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        github=None,  # type: ignore[arg-type]
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


class _RunGitRecorder:
    """Captures the argv passed to _run_git and returns canned output."""

    def __init__(self, output: str = "ok") -> None:
        self.calls: list[list[str]] = []
        self.output = output

    def __call__(self, args: list[str], *, cwd: str, env: dict[str, str] | None = None) -> str:
        self.calls.append([str(a) for a in args])
        return self.output


async def test_git_prefix_is_stripped_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _RunGitRecorder("clean tree")
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute({"command": "git status"})
    assert result.is_error is False, result.content[0]["text"]
    payload = json.loads(result.content[0]["text"])
    assert "clean tree" in payload["output"]
    assert recorder.calls == [["status"]]


async def test_duplicate_subcommand_arg_is_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute(
        {"command": "status", "args": ["status", "--porcelain"]}
    )
    assert result.is_error is False, result.content[0]["text"]
    assert recorder.calls == [["status", "--porcelain"]]


async def test_redundant_git_prefix_and_subcommand_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute(
        {"command": "git status", "args": ["status", "-s"]}
    )
    assert result.is_error is False, result.content[0]["text"]
    assert recorder.calls == [["status", "-s"]]


async def test_invalid_subcommand_after_normalization_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute({"command": "rm -rf"})
    assert result.is_error is True
    assert "invalid git subcommand" in result.content[0]["text"]
    assert recorder.calls == []
