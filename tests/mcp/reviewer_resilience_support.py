"""Shared helpers for plan 13 reviewer-resilience RED tests (W1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

Shell = Literal["disabled", "restricted", "enabled"]


def git_ctx(
    tmp_path: Path,
    *,
    shell: Shell = "restricted",
    push: Literal["disabled", "restricted", "enabled"] = "restricted",
    github: GitHubClient | None = None,
) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request"), shell=shell, push=push),
        github=github or GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


def init_git_repo(root: Path) -> None:
    import subprocess

    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    (root / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"], cwd=root, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "commit", "-m", "base"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def tool_error_text(result: object) -> str:
    from mergecraft.mcp.shared import ToolResult

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    return str(result.content[0]["text"])


def tool_payload(result: object) -> dict[str, Any]:
    from mergecraft.mcp.shared import ToolResult

    assert isinstance(result, ToolResult)
    assert result.is_error is False, result.content[0]["text"]
    return json.loads(result.content[0]["text"])
