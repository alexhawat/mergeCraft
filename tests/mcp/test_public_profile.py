"""MP1.1 — public HTTP mount profile guards."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.mcp.public_mcp_support import (
    _LIST_PAYLOAD,
    MCP_PUBLIC_ENDPOINT,
    build_public_http_client,
    init_git_repo,
    rpc_json,
    write_minimal_config,
)

from mergecraft.mcp.endpoints import mcp_role_url

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


def test_public_mount_does_not_expose_push_branch(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    client, ctx = build_public_http_client(tmp_path, monkeypatch)
    status, body = rpc_json(
        client,
        MCP_PUBLIC_ENDPOINT,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "push_branch", "arguments": {}},
        },
        auth_token=ctx.mcp_auth_token,
    )
    error = body.get("error")
    if status == 404:
        return
    assert isinstance(error, dict), body
    assert error.get("code") == -32601, body


def test_reviewer_mount_still_has_create_pull_request_review(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from mergecraft.cli.mcp_serve import build_mcp_app_from_ctx, build_mcp_tool_context
    from mergecraft.mcp.server import MCP_REVIEWER_ENDPOINT

    init_git_repo(tmp_path)
    write_minimal_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MERGECRAFT_MCP_TOKEN", "mp1-reviewer-guard")
    ctx = build_mcp_tool_context(cwd=tmp_path)
    client = TestClient(build_mcp_app_from_ctx("reviewer", ctx))
    _, body = rpc_json(
        client,
        MCP_REVIEWER_ENDPOINT,
        _LIST_PAYLOAD,
        auth_token=ctx.mcp_auth_token,
    )
    names = {entry["name"] for entry in body["result"]["tools"]}
    assert "create_pull_request_review" in names


def test_mcp_role_url_does_not_route_unknown_agents_to_public() -> None:
    base = "http://127.0.0.1:8765/mcp"
    for agent_id in (None, "claude", "codex", "unknown-agent"):
        url = mcp_role_url(base, agent_id)
        assert "/mcp/public" not in url
        assert url.endswith("/mcp/reviewer")
