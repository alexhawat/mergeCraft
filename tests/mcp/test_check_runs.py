"""Regression tests for check-run discovery MCP tool (issue #8 / D8, issue #266 / D13)."""

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
RUN_ID = 8484
RUN_NAME = "Verify (lint)"


class _RecordingGitHub(GitHubClient):
    """Records check-suite and check-run API calls made by the MCP tool under test."""

    def __init__(self) -> None:
        super().__init__(token="test-token")
        self.list_calls: list[tuple[str, str, str]] = []
        self.run_calls: list[tuple[str, str, str]] = []
        self.get_calls: list[int] = []

    async def list_check_runs_for_ref(
        self,
        owner: str,
        repo: str,
        ref: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.run_calls.append((owner, repo, ref))
        return {
            "total_count": 1,
            "check_runs": [
                {
                    "id": RUN_ID,
                    "name": RUN_NAME,
                    "head_sha": ref,
                    "status": "completed",
                    "conclusion": "failure",
                    "check_suite": {"id": SUITE_ID},
                }
            ],
        }

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
async def test_list_check_runs_tool_is_registered_under_its_own_name(tmp_path: Path) -> None:
    """The tool name is part of the agent contract — #266 renames the payload, not the tool."""
    check_runs = importlib.import_module("mergecraft.mcp.check_runs")
    ctx = _ctx(tmp_path, github=_RecordingGitHub())

    tool = check_runs.list_check_runs_tool(ctx)
    assert tool.list_entry()["name"] == "list_check_runs"

    names = {t.name for t in build_common_tools(ctx)}
    assert "list_check_runs" in names


@pytest.mark.asyncio
async def test_list_check_runs_calls_the_check_runs_endpoint(tmp_path: Path) -> None:
    """#266 — the tool must hit ``list_check_runs_for_ref``, never the suites sibling.

    Inverted from the pre-#266 assertion that pinned ``list_check_suites_for_ref``.
    """
    check_runs = importlib.import_module("mergecraft.mcp.check_runs")
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)

    await check_runs.list_check_runs_tool(ctx).execute({"ref": REF_SHA})

    assert github.run_calls == [("acme", "demo", REF_SHA)]
    assert github.list_calls == []


@pytest.mark.asyncio
async def test_list_check_runs_returns_check_run_data_for_ref(tmp_path: Path) -> None:
    """#266 — the payload key is ``check_runs`` and carries the runs the endpoint returned."""
    check_runs = importlib.import_module("mergecraft.mcp.check_runs")
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)

    tool = check_runs.list_check_runs_tool(ctx)
    payload = json.loads((await tool.execute({"ref": REF_SHA})).content[0]["text"])

    assert payload["ref"] == REF_SHA
    assert payload["total_count"] == 1
    assert "check_suites" not in payload
    runs = payload["check_runs"]
    assert [run["id"] for run in runs] == [RUN_ID]


@pytest.mark.asyncio
async def test_list_check_runs_preserves_the_run_shape_agents_navigate_by(
    tmp_path: Path,
) -> None:
    """#266 — a run carries its own name and its parent suite id, unlike a suite.

    The tool description sends the agent from this result to ``get_check_suite_logs``,
    which takes a *suite* id. On a check run that id lives at ``check_suite.id``, so the
    nesting must survive the swap or the documented follow-up call breaks.
    """
    check_runs = importlib.import_module("mergecraft.mcp.check_runs")
    ctx = _ctx(tmp_path, github=_RecordingGitHub())

    tool = check_runs.list_check_runs_tool(ctx)
    payload = json.loads((await tool.execute({"ref": REF_SHA})).content[0]["text"])

    run = payload["check_runs"][0]
    assert run["name"] == RUN_NAME
    assert run["check_suite"]["id"] == SUITE_ID


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
