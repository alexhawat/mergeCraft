"""Contract tests for ``get_check_suite_logs`` — must stay unchanged through K1 refactor (K2)."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
from tests.support.tool_context import bind_github_client

from mergecraft.mcp.check_suite import _analyze_log, get_check_suite_logs_tool
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

# Frozen contract shape
EXPECTED_JOB_KEYS = {
    "job_id",
    "job_name",
    "job_url",
    "log_index",
    "excerpt",
    "full_log_path",
}
EXPECTED_EXCERPT_KEYS = {"start_line", "end_line", "total_lines", "content"}
EXPECTED_NO_FAILURE_KEYS = {"check_suite_id", "message", "jobs"}


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
        if request.url.path.endswith("/logs"):
            return httpx.Response(200, content=self._payload)
        return httpx.Response(404)


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="unknown"), shell="restricted"),
        github=GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


def test_analyze_log_indexes_error_and_builds_excerpt() -> None:
    logs = (
        "Running tests\n"
        "##[error]Process completed with exit code 2.\n"
        "FAILED tests/ci/test_pipeline.py::test_normalize - AssertionError"
    )
    analysis = _analyze_log(logs)
    assert analysis["totalLines"] == 3
    assert analysis["index"]
    assert analysis["index"][0]["type"] in {"error", "failure"}
    assert "exit code 2" in analysis["excerpt"]["content"]


def test_analyze_log_tail_excerpt_when_no_error_marker() -> None:
    logs = "\n".join(f"line {index}" for index in range(1, 120))
    analysis = _analyze_log(logs, excerpt_lines=80)
    assert analysis["excerpt"]["startLine"] == 40
    assert analysis["excerpt"]["endLine"] == 119


def test_get_check_suite_logs_tool_schema_unchanged(tmp_path: Path) -> None:
    tool = get_check_suite_logs_tool(_ctx(tmp_path))
    entry = tool.list_entry()
    assert entry["name"] == "get_check_suite_logs"
    schema = entry["inputSchema"]
    assert schema["required"] == ["check_suite_id"]
    assert schema["properties"]["check_suite_id"]["type"] == "number"
    assert schema.get("additionalProperties") is False


@pytest.mark.asyncio
async def test_get_check_suite_logs_no_failures_message(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    bind_github_client(
        ctx,
        _FakeGitHub(
            runs=[
                {"id": 1, "conclusion": "success", "name": "ci", "html_url": "https://example.com"}
            ],
            log_bytes=b"",
        ),
    )
    payload = json.loads(
        (await get_check_suite_logs_tool(ctx).execute({"check_suite_id": 42})).content[0]["text"]
    )
    assert set(payload.keys()) == EXPECTED_NO_FAILURE_KEYS
    assert payload["check_suite_id"] == 42
    assert "no failed workflow runs" in payload["message"]
    assert payload["jobs"] == []
    assert "skipped" not in payload


@pytest.mark.asyncio
async def test_get_check_suite_logs_skips_when_github_client_unavailable(tmp_path: Path) -> None:
    from mergecraft.scm.gitlab import GitLabScmAdapter

    ctx = _ctx(tmp_path)
    object.__setattr__(
        ctx,
        "scm",
        GitLabScmAdapter(token="test-token", base_url="https://gitlab.example/api/v4"),
    )
    payload = json.loads(
        (await get_check_suite_logs_tool(ctx).execute({"check_suite_id": 42})).content[0]["text"]
    )
    assert payload["check_suite_id"] == 42
    assert payload["jobs"] == []
    assert payload["skipped"] is True
    assert payload["available"] is False
    assert "unavailable" in payload["message"]
    assert "no failed workflow runs" not in payload["message"]


@pytest.mark.asyncio
async def test_get_check_suite_logs_listing_failure_is_unavailable_not_an_error(
    tmp_path: Path,
) -> None:
    class _ListingFailGitHub(GitHubClient):
        async def list_workflow_runs_for_check_suite(
            self, *_args: object, **_kwargs: object
        ) -> list[dict[str, object]]:
            msg = "boom"
            raise RuntimeError(msg)

    ctx = _ctx(tmp_path)
    bind_github_client(ctx, _ListingFailGitHub(token="test-token"))
    result = await get_check_suite_logs_tool(ctx).execute({"check_suite_id": 42})
    assert result.is_error is False
    payload = json.loads(result.content[0]["text"])
    assert payload["available"] is False
    assert payload["jobs"] == []
    assert payload["check_suite_id"] == 42
    assert payload["skipped"] is False
    assert "boom" in payload["message"]


@pytest.mark.asyncio
async def test_get_check_suite_logs_incomplete_listing_is_unavailable(
    tmp_path: Path,
) -> None:
    from mergecraft.utils.github import GitHubListedItems

    class _IncompleteGitHub(GitHubClient):
        async def list_workflow_runs_for_check_suite(
            self, *_args: object, **_kwargs: object
        ) -> GitHubListedItems:
            return GitHubListedItems(
                items=[{"id": 1, "conclusion": "failure", "name": "ci"}],
                incomplete=True,
            )

    ctx = _ctx(tmp_path)
    bind_github_client(ctx, _IncompleteGitHub(token="test-token"))
    result = await get_check_suite_logs_tool(ctx).execute({"check_suite_id": 42})
    payload = json.loads(result.content[0]["text"])
    assert result.is_error is False
    assert payload["available"] is False
    assert payload["jobs"] == []
    assert "incomplete" in payload["message"]


@pytest.mark.asyncio
async def test_get_check_suite_logs_return_shape_and_three_run_cap(tmp_path: Path) -> None:
    log_body = "step one\n##[error]Process completed with exit code 2.\n"
    zbuf = BytesIO()
    with zipfile.ZipFile(zbuf, "w") as zf:
        zf.writestr("0_demo.txt", log_body)
    log_bytes = zbuf.getvalue()

    runs = [
        {
            "id": index,
            "conclusion": "failure",
            "name": f"job-{index}",
            "html_url": f"https://example.com/runs/{index}",
        }
        for index in range(1, 6)
    ]
    ctx = _ctx(tmp_path)
    bind_github_client(ctx, _FakeGitHub(runs=runs, log_bytes=log_bytes))

    payload = json.loads(
        (await get_check_suite_logs_tool(ctx).execute({"check_suite_id": 99})).content[0]["text"]
    )
    assert payload["check_suite_id"] == 99
    assert payload["count"] == 3
    assert len(payload["jobs"]) == 3
    for job in payload["jobs"]:
        assert set(job.keys()) == EXPECTED_JOB_KEYS
        assert set(job["excerpt"].keys()) == EXPECTED_EXCERPT_KEYS
        assert job["excerpt"]["content"]
        assert job["full_log_path"].startswith(str(tmp_path))
