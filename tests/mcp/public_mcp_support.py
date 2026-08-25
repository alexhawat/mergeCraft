"""Shared helpers for public MCP product tests (MP1)."""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

import pytest
from tests.ci.workflow_support import REPO_ROOT
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.mcp.endpoints import MCP_PUBLIC_ENDPOINT
from mergecraft.mcp.public import PUBLIC_TOOL_NAMES

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


def minimal_valid_finding_dict(
    fingerprint: str,
    *,
    index: int = 0,
    message: str | None = None,
) -> dict[str, Any]:
    """Build one ``Finding``-valid row with ``short_id`` for public MCP tests."""
    from mergecraft.analyzers.finding import finding_short_id, make_finding

    finding = make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message=message or f"finding {index}",
        path="demo.py",
        start_line=1,
        end_line=1,
        source="analyzer",
        introduced_by_pr="unknown",
        fingerprint=fingerprint,
    )
    row = finding.model_dump(mode="json")
    row["short_id"] = finding_short_id(fingerprint)
    return row


RUNTIME_PRIMITIVE_SAMPLES: tuple[str, ...] = (
    "checkout_pr",
    "create_pull_request_review",
)

_LIST_PAYLOAD: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
_INIT_PAYLOAD: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 0,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "mp1-test", "version": "0"},
    },
}

cli_runner = CliRunner()


def import_module(dotted: str) -> Any:
    return importlib.import_module(dotted)


def init_git_repo(tmp_path: Path) -> None:
    if (tmp_path / ".git").exists():
        return
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


def write_minimal_config(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        "models:\n  - anthropic/claude-sonnet\n",
        encoding="utf-8",
    )


def mcp_list_names(*, role: str, cwd: Path) -> list[str]:
    result = cli_runner.invoke(
        app,
        ["mcp", "list", "--role", role, "--cwd", str(cwd)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def build_public_http_client(tmp_path: Path, monkeypatch: MonkeyPatch) -> Any:
    """Build an authenticated TestClient for the public HTTP mount (MP2)."""
    from fastapi.testclient import TestClient

    from mergecraft.cli.mcp_serve import build_mcp_app_from_ctx, build_mcp_tool_context

    init_git_repo(tmp_path)
    write_minimal_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MERGECRAFT_MCP_TOKEN", "mp1-public-test-token")
    ctx = build_mcp_tool_context(cwd=tmp_path)
    return TestClient(build_mcp_app_from_ctx("public", ctx)), ctx


def rpc_json(
    client: Any,
    endpoint: str,
    payload: dict[str, Any],
    *,
    auth_token: str | None = None,
) -> tuple[int, dict[str, Any]]:
    headers: dict[str, str] = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    response = client.post(endpoint, headers=headers, json=payload)
    body = response.json()
    assert isinstance(body, dict), body
    return response.status_code, body


def is_auth_rejection(status_code: int, body: dict[str, Any]) -> bool:
    if status_code == 401:
        return True
    error = body.get("error")
    return isinstance(error, dict) and error.get("code") in {-32600, -32001}


def _mergecraft_argv() -> list[str]:
    venv_bin = REPO_ROOT / ".venv" / "bin" / "mergecraft"
    if venv_bin.is_file():
        return [str(venv_bin)]
    binary = shutil.which("mergecraft")
    if binary:
        return [binary]
    pytest.fail("mergecraft CLI not found on PATH or in .venv/bin")


def stdio_rpc_exchange(
    tmp_path: Path,
    *,
    role: str,
    transport: str,
    request: dict[str, Any],
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Send one JSON-RPC line to a stdio MCP serve subprocess."""
    proc = subprocess.Popen(
        [
            *_mergecraft_argv(),
            "mcp",
            "serve",
            "--role",
            role,
            "--transport",
            transport,
            "--cwd",
            str(tmp_path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=tmp_path,
        text=True,
    )
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        assert line.strip(), f"stdio serve produced no stdout (stderr={proc.stderr.read()})"
        parsed = json.loads(line)
        assert isinstance(parsed, dict), parsed
        return parsed
    finally:
        proc.terminate()
        proc.wait(timeout=timeout)


__all__ = [
    "MCP_PUBLIC_ENDPOINT",
    "PUBLIC_TOOL_NAMES",
    "RUNTIME_PRIMITIVE_SAMPLES",
    "_INIT_PAYLOAD",
    "_LIST_PAYLOAD",
    "build_public_http_client",
    "cli_runner",
    "import_module",
    "init_git_repo",
    "is_auth_rejection",
    "mcp_list_names",
    "minimal_valid_finding_dict",
    "rpc_json",
    "stdio_rpc_exchange",
    "write_minimal_config",
]
