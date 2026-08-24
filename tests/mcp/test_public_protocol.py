"""MP1.5 — public profile protocol conformance (RED until MP5)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from tests.mcp.public_mcp_support import (
    _INIT_PAYLOAD,
    _LIST_PAYLOAD,
    MCP_PUBLIC_ENDPOINT,
    PUBLIC_TOOL_NAMES,
    build_public_http_client,
    is_auth_rejection,
    rpc_json,
)

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


def _initialize(client: Any, auth_token: str) -> dict[str, Any]:
    _, body = rpc_json(
        client,
        MCP_PUBLIC_ENDPOINT,
        _INIT_PAYLOAD,
        auth_token=auth_token,
    )
    return body


def test_initialize_then_tools_list(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    client, ctx = build_public_http_client(tmp_path, monkeypatch)
    init_body = _initialize(client, ctx.mcp_auth_token)
    assert "result" in init_body, init_body
    _, list_body = rpc_json(
        client,
        MCP_PUBLIC_ENDPOINT,
        _LIST_PAYLOAD,
        auth_token=ctx.mcp_auth_token,
    )
    names = {entry["name"] for entry in list_body["result"]["tools"]}
    assert names == set(PUBLIC_TOOL_NAMES)


def test_unauthenticated_http_tools_list_rejected(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    client, _ctx = build_public_http_client(tmp_path, monkeypatch)
    status, body = rpc_json(client, MCP_PUBLIC_ENDPOINT, _LIST_PAYLOAD)
    assert is_auth_rejection(status, body), (status, body)


def test_authenticated_tools_call_get_capabilities(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    client, ctx = build_public_http_client(tmp_path, monkeypatch)
    _initialize(client, ctx.mcp_auth_token)
    _, body = rpc_json(
        client,
        MCP_PUBLIC_ENDPOINT,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_capabilities", "arguments": {}},
        },
        auth_token=ctx.mcp_auth_token,
    )
    assert "result" in body, body
    payload = json.loads(body["result"]["content"][0]["text"])
    assert payload.get("review_only") is True


def test_unknown_tool_jsonrpc_error(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    client, ctx = build_public_http_client(tmp_path, monkeypatch)
    _, body = rpc_json(
        client,
        MCP_PUBLIC_ENDPOINT,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "not_a_public_tool", "arguments": {}},
        },
        auth_token=ctx.mcp_auth_token,
    )
    error = body.get("error")
    assert isinstance(error, dict), body
    assert error.get("code") == -32601, body


def test_schema_error_on_inspect_finding_missing_id(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    client, ctx = build_public_http_client(tmp_path, monkeypatch)
    _, body = rpc_json(
        client,
        MCP_PUBLIC_ENDPOINT,
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "inspect_finding", "arguments": {}},
        },
        auth_token=ctx.mcp_auth_token,
    )
    error = body.get("error")
    assert isinstance(error, dict), body
    assert error.get("code") in {-32602, -32603}, body


def test_large_findings_result_is_json(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from mergecraft.review.completed import CompletedReview, persist_completed_review
    from mergecraft.review.snapshot import canonical_review_snapshot

    review_id = "mp1-large-findings"
    findings = [
        {
            "fingerprint": f"{index:064x}",
            "short_id": f"MC-{index:06x}",
            "message": f"finding {index}",
            "severity": "minor",
        }
        for index in range(200)
    ]
    persist_completed_review(
        CompletedReview(
            review_id=review_id,
            snapshot=canonical_review_snapshot(entry="cli"),
            manifest={"outcome": "changes_requested"},
            findings=findings,
        ),
        repo_root=tmp_path,
    )
    client, ctx = build_public_http_client(tmp_path, monkeypatch)
    _, body = rpc_json(
        client,
        MCP_PUBLIC_ENDPOINT,
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "get_review", "arguments": {"review_id": review_id}},
        },
        auth_token=ctx.mcp_auth_token,
    )
    assert "result" in body, body
    text = body["result"]["content"][0]["text"]
    parsed = json.loads(text)
    assert isinstance(parsed.get("findings"), list)
    assert len(parsed["findings"]) == len(findings)
