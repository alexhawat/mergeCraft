"""Shared fixtures for DG9 SCM abstraction RED suite."""

from __future__ import annotations

from typing import Any

import httpx

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

try:  # pragma: no cover — collection guard until DG9.2 lands ``mergecraft.scm``.
    from mergecraft.scm import protocol as _scm_protocol_mod

    _SCM_AVAILABLE = True
except ImportError:
    _SCM_AVAILABLE = False
    _scm_protocol_mod = None  # type: ignore[assignment]


def require_scm() -> None:
    """Hard gate for impl-pending tests — missing module is an assertion failure."""
    assert _SCM_AVAILABLE, "mergecraft.scm not implemented yet (DG9.2)"


class RecordingGitHubClient(GitHubClient):
    """GitHub client that records REST/GraphQL calls for behavioural snapshots."""

    def __init__(self, *, transport: httpx.MockTransport) -> None:
        super().__init__(
            "snapshot-token",
            client=httpx.AsyncClient(
                transport=transport,
                base_url="https://api.github.com",
                headers={"Authorization": "Bearer snapshot-token"},
            ),
        )
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        self.calls.append(
            (
                method.upper(),
                path,
                {
                    "params": dict(params or {}),
                    "json": json,
                    "headers": dict(headers or {}),
                },
            )
        )
        return await super().request(
            method,
            path,
            params=params,
            json=json,
            headers=headers,
        )


def github_snapshot_transport() -> httpx.MockTransport:
    """Deterministic GitHub API responses for the pre-extraction behavioural pin."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/acme/demo/pulls/7":
            return httpx.Response(
                200,
                json={
                    "number": 7,
                    "html_url": "https://github.com/acme/demo/pull/7",
                    "title": "Add widgets",
                    "body": "Summary",
                    "state": "open",
                    "draft": False,
                    "merged": False,
                    "maintainer_can_modify": True,
                    "head": {
                        "ref": "feature/widgets",
                        "sha": "abc123def456",
                        "repo": {
                            "full_name": "acme/demo",
                            "clone_url": "https://github.com/acme/demo.git",
                        },
                    },
                    "base": {
                        "ref": "main",
                        "repo": {"full_name": "acme/demo"},
                    },
                    "user": {"login": "dev1"},
                    "assignees": [],
                    "labels": [{"name": "enhancement"}],
                },
            )
        if path == "/graphql":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "closingIssuesReferences": {
                                    "nodes": [{"number": 42, "title": "Track widgets"}]
                                }
                            }
                        }
                    }
                },
            )
        if path == "/repos/acme/demo/issues/42/comments":
            if request.method == "POST":
                return httpx.Response(
                    201,
                    json={
                        "id": 9002,
                        "body": "Progress update\n\n---\n*via mergecraft*",
                        "html_url": "https://github.com/acme/demo/issues/42#issuecomment-9002",
                    },
                )
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 9001,
                        "body": "Looks good",
                        "user": {"login": "reviewer"},
                    }
                ],
            )
        if path == "/repos/acme/demo/pulls/7/reviews":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 501,
                        "body": "*via mergecraft*\nSummary",
                        "commit_id": "deadbeef00000000000000000000000000000000",
                        "state": "COMMENTED",
                    }
                ],
            )
        if path == "/repos/acme/demo/commits/abc123def456":
            return httpx.Response(
                200,
                json={
                    "sha": "abc123def456",
                    "html_url": "https://github.com/acme/demo/commit/abc123def456",
                    "commit": {
                        "message": "Add widgets",
                        "author": {"date": "2026-08-18T00:00:00Z"},
                    },
                    "author": {"login": "dev1"},
                    "committer": {"login": "dev1"},
                    "parents": [],
                    "files": [],
                    "stats": {"additions": 1, "deletions": 0, "total": 1},
                },
            )
        if path == "/repos/acme/demo/commits/main/check-suites":
            return httpx.Response(200, json={"total_count": 1, "check_suites": [{"id": 11}]})
        if path == "/repos/acme/demo/commits/main/check-runs":
            return httpx.Response(
                200,
                json={
                    "total_count": 1,
                    "check_runs": [{"id": 21, "name": "lint", "check_suite": {"id": 11}}],
                },
            )
        return httpx.Response(404, json={"message": f"unexpected path {path}"})

    return httpx.MockTransport(handler)


def tool_ctx(tmp_path: Any, *, github: GitHubClient | None = None) -> ToolContext:
    """Minimal ToolContext wired for SCM snapshot exercises."""
    path = str(tmp_path)
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=7, is_pr=True),
            shell="restricted",
        ),
        github=github or GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=path),
        mcp_server_url="",
        tmpdir=path,
        pr_approve_enabled=True,
        trust_tier="trusted",
    )
