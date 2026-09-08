"""#620 — consumer MCP servers are fail-closed and read-only."""

from __future__ import annotations

import json
from pathlib import Path

from mergecraft.review.consumer_mcp import (
    load_consumer_mcp_servers,
    validate_consumer_mcp_server,
)


def test_rejects_oauth_and_write_tools() -> None:
    assert (
        validate_consumer_mcp_server({"command": "mergecraft", "oauth": True}, name="docs") is None
    )
    assert (
        validate_consumer_mcp_server(
            {"command": "mergecraft", "tools": ["create_issue"]},
            name="docs",
        )
        is None
    )


def test_rejects_url_only_server() -> None:
    assert validate_consumer_mcp_server({"url": "https://example.com/mcp"}, name="docs") is None


def test_untrusted_tier_loads_nothing(tmp_path: Path) -> None:
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "mcp.json").write_text(
        json.dumps({"mcpServers": {"x": {"command": "bash", "args": ["-c", "id"]}}}),
        encoding="utf-8",
    )
    assert load_consumer_mcp_servers(tmp_path, trust_tier="untrusted") == []
    assert (
        load_consumer_mcp_servers(
            tmp_path,
            configured=[{"name": "docs", "command": "uv"}],
            trust_tier="untrusted",
        )
        == []
    )


def test_loads_vscode_mcp_json(tmp_path: Path) -> None:
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "catalog": {
                        "command": "uv",
                        "args": ["run", "catalog-mcp"],
                        "tools": ["search_docs"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    servers = load_consumer_mcp_servers(tmp_path, trust_tier="trusted")
    assert [server.name for server in servers] == ["catalog"]
    assert servers[0].command == "uv"
