"""#283 / D16: Codex MCP auth is a Unix-domain socket, not invented ``http_headers``.

W0.6 recorded **unix-socket**: ``agents/codex.py`` documents that
``http_headers`` is not a verified Codex MCP config key and an unverified
key could break the review. Batch O must not invent ``http_headers``.
Codex presents the per-run token (or peercred) over a Unix-domain socket
or a Codex-documented equivalent.
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
    """D16 control: Codex MCP table must not grow an unverified ``http_headers`` key."""
    codex_module = _load_codex_module()
    ctx = make_agent_run_context(tmp_path, resolved_model="openai/gpt-5.3-codex")
    ctx.payload.shell = "disabled"

    config_path = Path(codex_module.write_mcp_config(ctx))
    server_block = _mergecraft_server_block(config_path.read_text(encoding="utf-8"))
    assert "http_headers" not in server_block
    assert "Authorization" not in server_block


def test_codex_mcp_config_uses_unix_domain_socket(tmp_path: Path) -> None:
    """W11.4 Codex case: Unix-domain socket (or Codex-documented equivalent), plus token/peercred."""
    codex_module = _load_codex_module()
    ctx = make_agent_run_context(tmp_path, resolved_model="openai/gpt-5.3-codex")
    ctx.payload.shell = "disabled"
    ctx.mcp_server_url = "http://127.0.0.1:3764/mcp"

    config_path = Path(codex_module.write_mcp_config(ctx))
    text = config_path.read_text(encoding="utf-8")
    server_block = _mergecraft_server_block(text)

    assert "http_headers" not in server_block
    uses_unix = (
        "unix://" in server_block
        or "unix:" in server_block
        or ".sock" in server_block
        or "unix_socket" in server_block
        or "uds" in server_block
        or "socket_path" in server_block
    )
    assert uses_unix, (
        "Codex MCP auth must use a Unix-domain socket (D16), not HTTP headers; "
        f"server block was:\n{server_block}"
    )
    # Loopback HTTP URL is the pre-W14 transport and is not Codex-legal for the token.
    assert "http://127.0.0.1" not in server_block
    assert "http://localhost" not in server_block
