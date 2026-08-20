"""#283 / D16: Codex MCP config uses documented ``url`` + ``bearer_token_env_var``.

W0.6 recorded that ``http_headers`` is not a verified Codex MCP config key and
that ``socket_path`` is also undocumented. The documented Codex transports are
stdio ``command`` and HTTP ``url`` with optional ``bearer_token_env_var``. The
per-run MCP bearer token is injected via ``MERGECRAFT_MCP_TOKEN`` so Codex can
authenticate without inventing unverified config keys.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from tests.agents.conftest import make_agent_run_context


def _load_codex_module():
    try:
        return importlib.import_module("mergecraft.agents.codex")
    except ImportError as exc:
        pytest.fail(f"mergecraft.agents.codex not implemented: {exc}")


def _mergecraft_server_block(text: str) -> str:
    marker = "[mcp_servers.mergecraft]"
    assert marker in text, text
    rest = text.split(marker, 1)[1]
    next_table = rest.find("\n[")
    return rest if next_table < 0 else rest[:next_table]


def test_codex_mcp_config_does_not_invent_http_headers(tmp_path: Path) -> None:
    """D16 control: Codex MCP table must not use the unverified ``http_headers`` key."""
    codex_module = _load_codex_module()
    ctx = make_agent_run_context(tmp_path, resolved_model="openai/gpt-5.3-codex")
    ctx.payload.shell = "disabled"

    config_path = Path(codex_module.write_mcp_config(ctx))
    server_block = _mergecraft_server_block(config_path.read_text(encoding="utf-8"))
    assert "http_headers" not in server_block
    assert "Authorization" not in server_block


def test_codex_mcp_config_uses_documented_http_transport(tmp_path: Path) -> None:
    """D16: Codex MCP config uses the documented ``url`` + ``bearer_token_env_var`` transport.

    ``socket_path`` is not a documented Codex config key. The authenticated HTTP
    transport with ``bearer_token_env_var`` lets Codex present the per-run token
    via the ``MERGECRAFT_MCP_TOKEN`` env var without inventing unverified keys.
    """
    codex_module = _load_codex_module()
    ctx = make_agent_run_context(tmp_path, resolved_model="openai/gpt-5.3-codex")
    ctx.payload.shell = "disabled"
    ctx.mcp_server_url = "http://127.0.0.1:3764/mcp"

    config_path = Path(codex_module.write_mcp_config(ctx))
    text = config_path.read_text(encoding="utf-8")
    server_block = _mergecraft_server_block(text)

    assert "http_headers" not in server_block
    assert "socket_path" not in server_block
    # Documented HTTP transport with env-var-carried bearer token.
    assert "url" in server_block
    assert "bearer_token_env_var" in server_block
    assert "MERGECRAFT_MCP_TOKEN" in server_block


def test_codex_mcp_config_writes_verifier_server_entry(tmp_path: Path) -> None:
    """Codex subagents inherit a dedicated ``mergecraft-verifier`` MCP entry (D9 parity)."""
    from mergecraft.mcp.endpoints import MCP_REVIEWER_ENDPOINT, MCP_VERIFIER_ENDPOINT
    from mergecraft.types import MERGECRAFT_VERIFIER_MCP_NAME

    codex_module = _load_codex_module()
    ctx = make_agent_run_context(tmp_path, resolved_model="openai/gpt-5.3-codex")
    ctx.payload.shell = "disabled"
    ctx.mcp_server_url = "http://127.0.0.1:3764/mcp"

    config_path = Path(codex_module.write_mcp_config(ctx))
    text = config_path.read_text(encoding="utf-8")
    assert f"[mcp_servers.{MERGECRAFT_VERIFIER_MCP_NAME}]" in text
    verifier_block = text.split(f"[mcp_servers.{MERGECRAFT_VERIFIER_MCP_NAME}]", 1)[1]
    next_table = verifier_block.find("\n[")
    verifier_block = verifier_block if next_table < 0 else verifier_block[:next_table]
    assert MCP_VERIFIER_ENDPOINT in verifier_block
    assert MCP_REVIEWER_ENDPOINT not in verifier_block
