"""Tests for MCP tool registry listing."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.server import build_orchestrator_tools
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.types import XrepoConfig
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

EXPECTED_CORE_TOOLS = {
    "start_dependency_installation",
    "await_dependency_installation",
    "create_issue_comment",
    "edit_issue_comment",
    "reply_to_review_comment",
    "report_progress",
    "create_issue",
    "close_issue",
    "reopen_issue",
    "get_issue",
    "get_issue_comments",
    "get_issue_events",
    "create_pull_request_review",
    "get_pull_request",
    "get_commit_info",
    "checkout_pr",
    "get_review_comments",
    "list_pull_request_reviews",
    "resolve_review_thread",
    "get_check_suite_logs",
    "add_labels",
    "remove_labels",
    "git",
    "git_fetch",
    "run_static_checks",
    "push_branch",
    "push_tags",
    "delete_branch",
    "upload_file",
    "set_output",
    "shell",
    "kill_background",
    "select_mode",
    "create_pull_request",
    "update_pull_request_body",
    "close_pull_request",
}


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
        xrepo=XrepoConfig(mode="explicit", read=["other"], write=["other"]),
        static_checks_enabled=True,
    )


def test_orchestrator_tool_registry_lists_expected_names(tool_ctx: ToolContext) -> None:
    tools = build_orchestrator_tools(tool_ctx)
    names = {t.name for t in tools}
    missing = EXPECTED_CORE_TOOLS - names
    assert not missing, f"missing tools: {sorted(missing)}"
    assert "commit_changes" in names  # signed_commits=True
    assert "list_repos" in names
    assert "checkout_repo" in names
    assert len(tools) >= len(EXPECTED_CORE_TOOLS)


def test_tool_list_entries_have_schemas(tool_ctx: ToolContext) -> None:
    tools = build_orchestrator_tools(tool_ctx)
    for t in tools:
        entry = t.list_entry()
        assert entry["name"] == t.name
        assert "description" in entry
        assert "inputSchema" in entry
        assert entry["inputSchema"].get("type") == "object"


def test_mutates_flag_marks_state_changing_tools(tool_ctx: ToolContext) -> None:
    tools = {t.name: t for t in build_orchestrator_tools(tool_ctx)}
    assert tools["create_issue_comment"].mutates is True
    assert tools["push_branch"].mutates is True
    assert tools["get_issue"].mutates is False
    assert tools["git"].mutates is False
    assert tools["shell"].mutates is False


def test_start_mcp_http_server_returns_url(tool_ctx: ToolContext) -> None:
    from mergecraft.mcp.server import start_mcp_http_server

    url, stop = start_mcp_http_server(tool_ctx)
    try:
        assert url.startswith("http://127.0.0.1:")
        assert url.endswith("/mcp")
        port = int(url.split(":")[2].split("/")[0])
        assert port >= 3764
    finally:
        stop()
