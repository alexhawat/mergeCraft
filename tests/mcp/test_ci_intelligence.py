"""MCP tool tests for analyze_ci_failures (K3 runtime seam)."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
from tests.ci.support import CI_SECTION_HEADING, load_fixture

from mergecraft.mcp.ci_intelligence import analyze_ci_failures_tool
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient


class _FakeGitHub(GitHubClient):
    def __init__(self, *, runs: list[dict[str, Any]], log_bytes: bytes) -> None:
        client = httpx.AsyncClient(
            base_url="https://api.github.com",
            transport=_RecordingTransport(log_bytes),
        )
        super().__init__(token="test-token", client=client)
        self._runs = runs

    async def get(self, path: str, **kwargs: Any) -> Any:
        if path.endswith("/actions/runs"):
            return {"workflow_runs": self._runs}
        return {}


class _RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=self._payload)


def _log_zip(text: str) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("0_build.txt", text)
    return buf.getvalue()


def _ctx(tmp_path: Path, github: GitHubClient) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="unknown"),
            shell="restricted",
            push="restricted",
        ),
        github=github,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        signed_commits=False,
        xrepo=None,
        static_checks_enabled=True,
    )


@pytest.mark.asyncio
async def test_analyze_ci_failures_tool_returns_review_payload(tmp_path: Path) -> None:
    fixture = load_fixture("pre_existing_unrelated_failure.json")
    log_text = str(fixture["jobs"][0]["log_excerpt"])
    runs = [
        {"id": 99, "name": "Verify (drift gates)", "conclusion": "failure", "html_url": "http://x"}
    ]
    ctx = _ctx(tmp_path, _FakeGitHub(runs=runs, log_bytes=_log_zip(log_text)))
    tool = analyze_ci_failures_tool(ctx)

    raw = await tool.execute(
        {
            "check_suite_id": 42,
            "pr_diff_paths": fixture["pr_diff_paths"],
            "base_branch_status": fixture["base_branch"]["same_fingerprint_conclusion"],
        }
    )
    payload = json.loads(raw.content[0]["text"])

    assert payload["available"] is True
    assert CI_SECTION_HEADING in payload["section"]
    assert "**Blame verdict:**" in payload["section"]
    assert "**Flaky verdict:**" in payload["section"]
    assert "probably not this pr" in payload["section"].lower()
    assert payload["stats"]["prAttributedCount"] == 0
    assert payload["stats"]["clusterCount"] == 1
    assert "clusters" in payload["preMergeSummary"]


@pytest.mark.asyncio
async def test_analyze_ci_failures_tool_reports_provider_truncation(tmp_path: Path) -> None:
    fixture = load_fixture("truncation_overflow.json")
    log_text = str(fixture["failed_runs"][0]["log_excerpt"])
    runs = [
        {
            "id": 90000000000 + index,
            "name": run["job_name"],
            "conclusion": "failure",
            "html_url": f"http://x/{index}",
        }
        for index, run in enumerate(fixture["failed_runs"])
    ]
    ctx = _ctx(tmp_path, _FakeGitHub(runs=runs, log_bytes=_log_zip(log_text)))
    tool = analyze_ci_failures_tool(ctx)

    raw = await tool.execute({"check_suite_id": 42})
    payload = json.loads(raw.content[0]["text"])

    overflow = len(fixture["failed_runs"]) - 3
    assert payload["available"] is True
    assert payload["stats"]["truncated"] is True
    assert payload["stats"]["overflow"] == overflow
    assert payload["stats"]["failureCount"] == len(fixture["failed_runs"])
    assert str(overflow) in payload["section"] or "not analyzed" in payload["section"].lower()


@pytest.mark.asyncio
async def test_analyze_ci_failures_tool_no_failures(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _FakeGitHub(runs=[], log_bytes=b""))
    tool = analyze_ci_failures_tool(ctx)
    raw = await tool.execute({"check_suite_id": 7})
    payload = json.loads(raw.content[0]["text"])
    assert payload["available"] is False
    assert payload["stats"]["clusterCount"] == 0
