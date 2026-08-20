"""#346: Gemini, OpenCode, and Cursor harness configs pin MCP Bearer headers.

Mirror ``tests/agents/test_codex_mcp_unix_socket.py``. When ``ctx.mcp_auth_token`` is
set the rendered harness config must include ``Authorization: Bearer``; when empty
the Authorization header must be omitted (OpenCode omits the whole ``headers`` block).
W3 un-xfails these pins once coverage is reconciled.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from tests.agents.conftest import make_agent_run_context

from mergecraft.agents.shared import AgentRunContext
from mergecraft.types import MERGECRAFT_MCP_NAME

_PER_RUN_TOKEN = "test-mcp-bearer-pin-token"
_LOOPBACK_MCP_URL = "http://127.0.0.1:3764/mcp/reviewer"
_CLOUD_REACHABLE_MCP_URL = "https://mcp.example.com/mcp/reviewer"


def _load_module(module_name: str) -> ModuleType:
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        pytest.fail(f"{module_name} not implemented: {exc}")


def _ctx(
    tmp_path: Path,
    *,
    resolved_model: str,
    mcp_auth_token: str,
    mcp_server_url: str,
) -> AgentRunContext:
    ctx = make_agent_run_context(tmp_path, resolved_model=resolved_model)
    ctx.mcp_server_url = mcp_server_url
    ctx.mcp_auth_token = mcp_auth_token
    return ctx


def _authorization_header(headers: dict[str, Any] | None) -> str | None:
    if not headers:
        return None
    value = headers.get("Authorization")
    return value if isinstance(value, str) else None


@pytest.mark.xfail(reason="green after W3: gemini/opencode/cursor Bearer pins", strict=False)
def test_gemini_write_mcp_config_includes_bearer_when_token_set(tmp_path: Path) -> None:
    """Gemini ``settings.json`` must forward ``Authorization: Bearer`` when token is set."""
    gemini_module = _load_module("mergecraft.agents.gemini")
    ctx = _ctx(
        tmp_path,
        resolved_model="google/gemini-2.5-pro",
        mcp_auth_token=_PER_RUN_TOKEN,
        mcp_server_url=_LOOPBACK_MCP_URL,
    )

    config_path = gemini_module.write_mcp_config(ctx)
    settings = json.loads(Path(config_path).read_text(encoding="utf-8"))
    headers = settings["mcpServers"][MERGECRAFT_MCP_NAME].get("headers")
    assert _authorization_header(headers) == f"Bearer {_PER_RUN_TOKEN}"


@pytest.mark.xfail(reason="green after W3: gemini/opencode/cursor Bearer pins", strict=False)
def test_gemini_write_mcp_config_omits_bearer_when_token_empty(tmp_path: Path) -> None:
    """Gemini must not emit ``Authorization`` when ``ctx.mcp_auth_token`` is empty."""
    gemini_module = _load_module("mergecraft.agents.gemini")
    ctx = _ctx(
        tmp_path,
        resolved_model="google/gemini-2.5-pro",
        mcp_auth_token="",
        mcp_server_url=_LOOPBACK_MCP_URL,
    )

    config_path = gemini_module.write_mcp_config(ctx)
    settings = json.loads(Path(config_path).read_text(encoding="utf-8"))
    headers = settings["mcpServers"][MERGECRAFT_MCP_NAME].get("headers")
    assert _authorization_header(headers) is None


@pytest.mark.xfail(reason="green after W3: gemini/opencode/cursor Bearer pins", strict=False)
def test_opencode_build_security_config_includes_bearer_when_token_set(tmp_path: Path) -> None:
    """OpenCode security JSON must include Bearer headers when token is set."""
    opencode_module = _load_module("mergecraft.agents.opencode")
    ctx = _ctx(
        tmp_path,
        resolved_model="anthropic/claude-sonnet",
        mcp_auth_token=_PER_RUN_TOKEN,
        mcp_server_url=_LOOPBACK_MCP_URL,
    )

    config = json.loads(opencode_module.build_security_config(ctx, "anthropic/claude-sonnet"))
    headers = config["mcp"][MERGECRAFT_MCP_NAME].get("headers")
    assert _authorization_header(headers) == f"Bearer {_PER_RUN_TOKEN}"


@pytest.mark.xfail(reason="green after W3: gemini/opencode/cursor Bearer pins", strict=False)
def test_opencode_build_security_config_omits_headers_when_token_empty(tmp_path: Path) -> None:
    """OpenCode must omit the MCP ``headers`` block when no token was issued."""
    opencode_module = _load_module("mergecraft.agents.opencode")
    ctx = _ctx(
        tmp_path,
        resolved_model="anthropic/claude-sonnet",
        mcp_auth_token="",
        mcp_server_url=_LOOPBACK_MCP_URL,
    )

    config = json.loads(opencode_module.build_security_config(ctx, "anthropic/claude-sonnet"))
    assert "headers" not in config["mcp"][MERGECRAFT_MCP_NAME]


@pytest.mark.xfail(reason="green after W3: gemini/opencode/cursor Bearer pins", strict=False)
def test_cursor_build_mcp_servers_includes_bearer_when_token_set(tmp_path: Path) -> None:
    """Cursor cloud payload must include Bearer headers for reachable MCP URLs."""
    cursor_module = _load_module("mergecraft.agents.cursor")
    ctx = _ctx(
        tmp_path,
        resolved_model="cursor/auto",
        mcp_auth_token=_PER_RUN_TOKEN,
        mcp_server_url=_CLOUD_REACHABLE_MCP_URL,
    )

    servers = cursor_module._build_mcp_servers(ctx)
    assert len(servers) == 1
    headers = servers[0].get("headers")
    assert _authorization_header(headers) == f"Bearer {_PER_RUN_TOKEN}"


@pytest.mark.xfail(reason="green after W3: gemini/opencode/cursor Bearer pins", strict=False)
def test_cursor_build_mcp_servers_omits_headers_when_token_empty(tmp_path: Path) -> None:
    """Cursor must omit MCP ``headers`` when ``ctx.mcp_auth_token`` is empty."""
    cursor_module = _load_module("mergecraft.agents.cursor")
    ctx = _ctx(
        tmp_path,
        resolved_model="cursor/auto",
        mcp_auth_token="",
        mcp_server_url=_CLOUD_REACHABLE_MCP_URL,
    )

    servers = cursor_module._build_mcp_servers(ctx)
    assert len(servers) == 1
    assert "headers" not in servers[0]
