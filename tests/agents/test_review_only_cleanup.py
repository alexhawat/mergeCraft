"""Production review surfaces do not advertise or retry abandoned write operations."""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from tests.review.test_post_run_terminal_gate import _run_ctx, _tool_ctx

from mergecraft.agents.post_run import run_post_run_retry_loop
from mergecraft.agents.shared import AgentResult
from mergecraft.mcp.server import (
    build_orchestrator_tools,
    build_reviewer_tools,
    build_verifier_tools,
    create_mcp_app,
)
from mergecraft.modes import compute_modes

if TYPE_CHECKING:
    from pathlib import Path

_REMOVED = {
    "push_branch",
    "push_tags",
    "delete_branch",
    "commit_changes",
    "create_pull_request",
    "update_pull_request_body",
    "close_pull_request",
}


@pytest.mark.parametrize("signed", [False, True])
@pytest.mark.parametrize("push", ["disabled", "restricted", "enabled"])
def test_rpc_surfaces_omit_abandoned_write_tools(tmp_path: Path, signed: bool, push: str) -> None:
    ctx = _tool_ctx(tmp_path)
    ctx.modes = compute_modes("claude", signed_commits=signed)
    ctx.payload = replace(ctx.payload, push=push)
    app = create_mcp_app(
        build_orchestrator_tools(ctx),
        ctx,
        role_tools={"reviewer": build_reviewer_tools(ctx), "verifier": build_verifier_tools(ctx)},
        auth_token="test-token",
    )
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        for route in ("/mcp", "/mcp/reviewer", "/mcp/verifier"):
            listed = client.post(
                route, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
            ).json()
            assert not _REMOVED.intersection(t["name"] for t in listed["result"]["tools"])
            for name in _REMOVED:
                result = client.post(
                    route,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": {}},
                    },
                ).json()
                assert result["error"]["code"] == -32601


@pytest.mark.parametrize("mode", [None, "CustomReadOnly"])
async def test_dirty_online_review_does_not_request_a_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str | None
) -> None:
    await asyncio.to_thread(
        subprocess.run, ["git", "init", "-q", str(tmp_path)], check=True, capture_output=True
    )
    (tmp_path / "build-output.txt").write_text("generated output\n")
    monkeypatch.chdir(tmp_path)
    ctx = _tool_ctx(tmp_path)
    ctx.tool_state.selected_mode = mode
    prompts: list[str] = []

    async def resume(prompt: str) -> AgentResult:
        prompts.append(prompt)
        return AgentResult(success=True)

    await run_post_run_retry_loop(_run_ctx(ctx), initial=AgentResult(success=True), resume=resume)
    assert prompts == []


def test_missing_claude_binary_does_not_try_buffered_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.agents import claude, shared

    calls: list[object] = []

    def missing(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError("missing test claude")

    def buffered(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout='{"result": "fake success"}', stderr="")

    monkeypatch.setattr(shared.subprocess, "Popen", missing)
    monkeypatch.setattr(shared.subprocess, "run", buffered)
    result = claude._run_claude_once(
        cli="/missing/claude",
        prompt="review",
        ctx=_run_ctx(_tool_ctx(tmp_path)),
        mcp_config=str(tmp_path / "mcp.json"),
    )
    assert not result.success
    assert "missing test claude" in (result.error or "")
    assert calls == []


@pytest.mark.parametrize(
    ("key", "value"), [("event", "APPROVE"), ("pull_number", 99), ("commit_id", "other-sha")]
)
def test_review_wire_rejects_legacy_scope_and_event_keys(
    tmp_path: Path, key: str, value: object
) -> None:
    ctx = _tool_ctx(tmp_path)
    with TestClient(
        create_mcp_app(build_orchestrator_tools(ctx), ctx, auth_token="test-token"),
        headers={"Authorization": "Bearer test-token"},
    ) as client:
        result = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "create_pull_request_review",
                    "arguments": {"body": "review", key: value},
                },
            },
        ).json()
    assert result["error"]["code"] == -32602
    assert ctx.tool_state.pending_review_publication is None


@pytest.mark.parametrize("mode", [None, "Review", "CustomReadOnly", "Fix", "build"])
def test_rpc_mutation_gate_stays_closed_for_every_mode(tmp_path: Path, mode: str | None) -> None:
    ctx = _tool_ctx(tmp_path)
    ctx.tool_state.selected_mode = mode
    with TestClient(
        create_mcp_app(build_orchestrator_tools(ctx), ctx, auth_token="test-token"),
        headers={"Authorization": "Bearer test-token"},
    ) as client:
        result = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "shell",
                    "arguments": {"command": "echo forbidden", "description": "mutation probe"},
                },
            },
        ).json()
    assert result["result"]["isError"] is True
    assert "review-only" in result["result"]["content"][0]["text"]
