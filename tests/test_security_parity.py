"""Security and permission parity tests (offline)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.agents.gates import (
    build_claude_native_fs_denies,
    build_opencode_native_fs_permission,
    subagent_denied_tool_names,
)
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.server import build_common_tools, build_orchestrator_tools
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.types import format_mcp_tool_ref
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.secrets import (
    clear_env_allowlist,
    filter_env,
    sanitize_secret,
    set_env_allowlist,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def tool_ctx(tmp_path: Path) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="unknown"),
            shell="restricted",
            push="restricted",
        ),
        github=GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        signed_commits=True,
    )


def test_mutating_tools_flagged_for_subagent_deny(tool_ctx: ToolContext) -> None:
    names = subagent_denied_tool_names(tool_ctx)
    assert "push_branch" in names
    assert "create_issue" in names
    assert "commit_changes" in names
    assert "get_pull_request" not in names


def test_shell_tool_only_when_restricted(tmp_path: Path) -> None:
    base = {
        "agent_id": "claude",
        "repo": RepoIdentity(owner="acme", name="demo"),
        "github": GitHubClient(token="t"),
        "github_installation_token": "",
        "git_token": "",
        "api_token": "",
        "modes": compute_modes("claude"),
        "tool_state": init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        "mcp_server_url": "",
        "tmpdir": str(tmp_path),
    }
    restricted = ToolContext(
        **base,  # type: ignore[arg-type]
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="unknown"),
            shell="restricted",
            push="disabled",
        ),
    )
    disabled = ToolContext(
        **base,  # type: ignore[arg-type]
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="unknown"),
            shell="disabled",
            push="disabled",
        ),
    )
    assert "shell" in {t.name for t in build_common_tools(restricted)}
    assert "shell" not in {t.name for t in build_common_tools(disabled)}


def test_secret_filter_strips_disallowed_keys() -> None:
    clear_env_allowlist()
    set_env_allowlist("SAFE_FLAG")
    try:
        env = {
            "PATH": "/usr/bin",
            "ANTHROPIC_API_KEY": "sk-secret",
            "SAFE_FLAG": "1",
            "HOME": "/tmp/home",
        }
        filtered = filter_env(env)
        assert "ANTHROPIC_API_KEY" not in filtered
        assert filtered.get("SAFE_FLAG") == "1"
        assert "PATH" in filtered
    finally:
        clear_env_allowlist()


def test_sanitize_secret_trims_whitespace() -> None:
    assert sanitize_secret("K", "  token  ") == "token"
    assert sanitize_secret("K", "   ") is None


def test_native_fs_denies_cover_git() -> None:
    claude = build_claude_native_fs_denies(["/tmp/secrets"])
    assert any(".git" in d for d in claude)
    assert any("secrets" in d for d in claude)
    oc = build_opencode_native_fs_permission()
    assert oc["edit"][".git"] == "deny"  # type: ignore[index]


def test_mcp_tool_ref_format_differs_by_agent() -> None:
    assert format_mcp_tool_ref("claude", "git") == "mcp__mergecraft__git"
    assert format_mcp_tool_ref("opencode", "git") == "mergecraft_git"


def test_tool_specs_are_unique(tool_ctx: ToolContext) -> None:
    tools = build_orchestrator_tools(tool_ctx)
    names = [t.name for t in tools]
    assert len(names) == len(set(names))
