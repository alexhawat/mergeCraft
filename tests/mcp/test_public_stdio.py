"""MP1.3 — stdio transport for the public profile (RED until MP3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.mcp.public_mcp_support import (
    _LIST_PAYLOAD,
    MCP_PUBLIC_ENDPOINT,
    PUBLIC_TOOL_NAMES,
    build_public_http_client,
    init_git_repo,
    is_auth_rejection,
    rpc_json,
    stdio_rpc_exchange,
    write_minimal_config,
)
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()


@pytest.mark.xfail(strict=False, reason="green after MP3: stdio public tools/list")
def test_stdio_public_lists_six_tools(tmp_path: Path) -> None:
    init_git_repo(tmp_path)
    write_minimal_config(tmp_path)
    body = stdio_rpc_exchange(
        tmp_path,
        role="public",
        transport="stdio",
        request=_LIST_PAYLOAD,
    )
    tools = body.get("result", {}).get("tools")
    assert isinstance(tools, list), body
    names = {entry["name"] for entry in tools}
    assert names == set(PUBLIC_TOOL_NAMES)


@pytest.mark.xfail(strict=False, reason="green after MP3: stdio needs no bearer")
def test_stdio_does_not_require_bearer(tmp_path: Path) -> None:
    init_git_repo(tmp_path)
    write_minimal_config(tmp_path)
    body = stdio_rpc_exchange(
        tmp_path,
        role="public",
        transport="stdio",
        request=_LIST_PAYLOAD,
    )
    assert "result" in body, body
    assert "error" not in body or body["error"] is None


@pytest.mark.xfail(strict=False, reason="green after MP3: stdio non-public usage error")
def test_stdio_non_public_role_is_usage_error(tmp_path: Path) -> None:
    init_git_repo(tmp_path)
    write_minimal_config(tmp_path)
    result = runner.invoke(
        app,
        [
            "mcp",
            "serve",
            "--role",
            "reviewer",
            "--transport",
            "stdio",
            "--cwd",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 2


@pytest.mark.xfail(strict=False, reason="green after MP2: HTTP public bearer gate")
def test_http_public_still_requires_bearer(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    client, _ctx = build_public_http_client(tmp_path, monkeypatch)
    status, body = rpc_json(client, MCP_PUBLIC_ENDPOINT, _LIST_PAYLOAD)
    assert is_auth_rejection(status, body), (status, body)
