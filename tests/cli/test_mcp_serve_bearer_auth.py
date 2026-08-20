"""#345 / D9: ``mergecraft mcp serve`` must reject unauthenticated MCP RPC.

``build_mcp_app_for_role`` currently calls ``create_mcp_app`` with no ``auth_token``,
so reviewer ``tools/list`` and ``tools/call`` succeed without ``Authorization: Bearer``.
W2 mints a per-serve token, sets ``ctx.mcp_auth_token``, and passes ``auth_token=``
into ``create_mcp_app`` — same gate as ``start_mcp_http_server``.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from mergecraft.mcp.server import MCP_REVIEWER_ENDPOINT

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_LIST_PAYLOAD = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
_CALL_PAYLOAD = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
        "name": "create_pull_request_review",
        "arguments": {"body": "review", "event": "COMMENT"},
    },
}


def _init_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "mcp@test.local"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "MCP Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "demo.py").write_text("print(1)\n", encoding="utf-8")
    subprocess.run(["git", "add", "demo.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )


def _write_config(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        "models:\n  - anthropic/claude-sonnet\n",
        encoding="utf-8",
    )


def _reviewer_client(tmp_path: Path, monkeypatch: MonkeyPatch) -> TestClient:
    from mergecraft.cli.mcp_serve import build_mcp_app_for_role

    _init_git_repo(tmp_path)
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    return TestClient(build_mcp_app_for_role(cwd=tmp_path, role="reviewer"))


def _is_auth_rejection(status_code: int, body: dict[str, Any]) -> bool:
    if status_code == 401:
        return True
    error = body.get("error")
    return isinstance(error, dict) and error.get("code") == -32600


@pytest.mark.xfail(reason="green after W2: mcp serve Bearer auth", strict=False)
def test_reviewer_serve_rejects_unauthenticated_tools_list(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Reviewer ``tools/list`` without Bearer must be HTTP 401 or JSON-RPC ``-32600``."""
    client = _reviewer_client(tmp_path, monkeypatch)
    response = client.post(MCP_REVIEWER_ENDPOINT, json=_LIST_PAYLOAD)
    body = response.json()
    assert _is_auth_rejection(response.status_code, body), (
        f"unauthenticated tools/list must be 401 or JSON-RPC -32600; "
        f"got status={response.status_code} body={body!r}"
    )


@pytest.mark.xfail(reason="green after W2: mcp serve Bearer auth", strict=False)
def test_reviewer_serve_rejects_unauthenticated_tools_call(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Reviewer ``tools/call`` on a write tool without Bearer must not succeed."""
    client = _reviewer_client(tmp_path, monkeypatch)
    response = client.post(MCP_REVIEWER_ENDPOINT, json=_CALL_PAYLOAD)
    body = response.json()
    assert _is_auth_rejection(response.status_code, body), (
        f"unauthenticated tools/call must be 401 or JSON-RPC -32600; "
        f"got status={response.status_code} body={body!r}"
    )
