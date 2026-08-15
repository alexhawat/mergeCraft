"""Tests for agent registry resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.agents import agents, resolve_agent
from mergecraft.agents.gates import (
    GIT_NATIVE_WRITE_DENY_CLAUDE,
    GIT_NATIVE_WRITE_DENY_OPENCODE,
    subagent_denied_tool_names,
)
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path


def test_resolve_agent_claude_opencode_codex_gemini_and_cursor() -> None:
    claude = resolve_agent("claude")
    opencode = resolve_agent("opencode")
    codex_agent = resolve_agent("codex")
    gemini_agent = resolve_agent("gemini")
    cursor_agent = resolve_agent("cursor")
    assert claude.name == "claude"
    assert opencode.name == "opencode"
    assert codex_agent.name == "codex"
    assert gemini_agent.name == "gemini"
    assert cursor_agent.name == "cursor"
    assert set(agents) == {"claude", "codex", "cursor", "gemini", "opencode"}


def test_resolve_agent_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown agent"):
        resolve_agent("not-a-real-agent")


def test_subagent_denied_tools_derived_from_class_complement(tmp_path: Path) -> None:
    """H4 / D14 — subagent deny list is the complement of reviewer-allowed classes."""
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="unknown"),
            shell="restricted",
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
    denied = subagent_denied_tool_names(ctx)
    assert "push_branch" in denied
    assert "create_issue_comment" in denied
    assert "commit_changes" in denied
    # `checkout_pr` is class `scope` — reviewer-allowed, so off the subagent deny list.
    assert "checkout_pr" not in denied
    # Verification is not in the reviewer allow-list.
    assert "verify_agent_findings" in denied
    assert "git" not in denied
    assert "get_issue" not in denied
    assert len(denied) > 0


def test_native_fs_denies_present() -> None:
    assert ".git" in GIT_NATIVE_WRITE_DENY_OPENCODE
    assert "Edit(.git)" in GIT_NATIVE_WRITE_DENY_CLAUDE
