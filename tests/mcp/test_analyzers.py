"""``run_analyzers`` MCP tool (W7 integration)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.server import build_common_tools
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient


def _ctx(
    tmp_path: Path,
    *,
    shell: str = "restricted",
    analyzers_enabled: bool = True,
    tier: str = "trusted",
) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request"),
            shell=shell,  # type: ignore[arg-type]
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        analyzers_settings_enabled=analyzers_enabled,
        trust_tier=tier,  # type: ignore[arg-type]
    )


async def _run(ctx: ToolContext, **params: Any) -> dict[str, Any]:
    analyzers = __import__("mergecraft.mcp.analyzers", fromlist=["run_analyzers_tool"])
    result = await analyzers.run_analyzers_tool(ctx).execute(params)
    return json.loads(result.content[0]["text"])


@pytest.mark.asyncio
async def test_reports_not_run_when_nothing_enabled(tmp_path: Path) -> None:
    payload = await _run(_ctx(tmp_path), changed_files=[])
    assert payload["ran"] is False
    assert payload["reason"]
    assert payload["findingCount"] == 0
    if payload["analyzers"]:
        assert all(row["status"] == "unavailable" for row in payload["analyzers"])


@pytest.fixture
def fixture_repo() -> Path:
    from tests.analyzers.support import FIXTURE_REPO

    return FIXTURE_REPO


@pytest.mark.asyncio
async def test_per_analyzer_status_returned(tmp_path: Path, fixture_repo: Path) -> None:
    payload = await _run(
        _ctx(tmp_path),
        changed_files=[".github/workflows/broken.yml"],
        repo_root=str(fixture_repo),
    )
    assert "analyzers" in payload
    assert isinstance(payload["analyzers"], list)
    if payload["ran"]:
        assert all("status" in row for row in payload["analyzers"])


def test_tool_withheld_when_trust_tier_forbids(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, shell="disabled", analyzers_enabled=False)
    names = {t.name for t in build_common_tools(ctx)}
    assert "run_analyzers" not in names


def test_tool_withheld_on_untrusted_tier_when_disabled(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, tier="untrusted", analyzers_enabled=False)
    names = {t.name for t in build_common_tools(ctx)}
    assert "run_analyzers" not in names
