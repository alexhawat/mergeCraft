"""Regression tests for check-suite discovery MCP tool (issue #8 / D8)."""

from __future__ import annotations

import importlib
import json
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.server import build_common_tools
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

REF_SHA = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
SUITE_ID = 4242


class _RecordingGitHub(GitHubClient):
    """Records check-suite API calls made by the MCP tool under test."""

    def __init__(self) -> None:
        super().__init__(token="test-token")
        self.list_calls: list[tuple[str, str, str]] = []
        self.get_calls: list[int] = []

    async def list_check_suites_for_ref(
        self,
        owner: str,
        repo: str,
        ref: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.list_calls.append((owner, repo, ref))
        return {
            "total_count": 1,
            "check_suites": [
                {
                    "id": SUITE_ID,
                    "head_sha": ref,
                    "status": "completed",
                    "conclusion": "success",
                    "app": {"name": "GitHub Actions"},
                }
            ],
        }

    async def get_check_suite(
        self,
        owner: str,
        repo: str,
        check_suite_id: int,
    ) -> dict[str, Any]:
        self.get_calls.append(check_suite_id)
        return {
            "id": check_suite_id,
            "head_sha": REF_SHA,
            "status": "completed",
            "conclusion": "success",
        }


def _ctx(tmp_path: Path, *, github: GitHubClient | None = None) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request", is_pr=True)),
        github=github or GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


@pytest.mark.asyncio
async def test_list_check_runs_returns_check_suite_data_for_ref(tmp_path: Path) -> None:
    """New MCP tool must expose check suites for a ref via GitHubClient list/get helpers."""
    check_runs = importlib.import_module("mergecraft.mcp.check_runs")
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)

    tool = check_runs.list_check_runs_tool(ctx)
    entry = tool.list_entry()
    assert entry["name"] == "list_check_runs"

    names = {t.name for t in build_common_tools(ctx)}
    assert "list_check_runs" in names

    payload = json.loads((await tool.execute({"ref": REF_SHA})).content[0]["text"])
    assert payload["ref"] == REF_SHA
    suites = payload.get("check_suites") or payload.get("checkSuites")
    assert isinstance(suites, list)
    assert suites
    assert suites[0]["id"] == SUITE_ID

    assert github.list_calls == [("acme", "demo", REF_SHA)]


@pytest.mark.asyncio
async def test_get_check_suite_tool_returns_suite_detail(tmp_path: Path) -> None:
    """Companion tool must fetch one suite by id (GitHubClient.get_check_suite)."""
    check_runs = importlib.import_module("mergecraft.mcp.check_runs")
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)

    get_tool = getattr(check_runs, "get_check_suite_tool", None)
    assert get_tool is not None, "W7 must expose get_check_suite alongside list_check_runs"

    tool = get_tool(ctx)
    payload = json.loads((await tool.execute({"check_suite_id": SUITE_ID})).content[0]["text"])
    assert payload["id"] == SUITE_ID
    assert github.get_calls == [SUITE_ID]
