"""Read-only consumer MCP servers attached during mergeCraft review (#620).

Sources, in order: ``review.mcpServers`` in committed config, then
``.vscode/mcp.json`` / ``.mcp.json`` when present. Fail closed on OAuth
remotes, write-capable declarations, and missing command/url.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from pathlib import Path

_RESERVED_NAMES = frozenset({"mergecraft", "mergecraft-verifier"})
_WRITE_HINTS = frozenset({"write", "create", "delete", "update", "push", "apply", "patch"})
_DISCOVERY_FILES = (".vscode/mcp.json", ".mcp.json")


@dataclass(frozen=True, slots=True)
class ConsumerMcpServer:
    """One allowlisted read-only MCP server for the review agent."""

    name: str
    command: str | None
    args: tuple[str, ...]
    url: str | None
    tools: tuple[str, ...]

    def as_stdio_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {"command": self.command or "", "args": list(self.args)}
        if self.tools:
            entry["tools"] = list(self.tools)
        return entry


def _looks_like_write_tool(name: str) -> bool:
    lowered = name.strip().casefold()
    return any(hint in lowered for hint in _WRITE_HINTS)


def validate_consumer_mcp_server(raw: dict[str, Any], *, name: str) -> ConsumerMcpServer | None:
    """Return a server or None when the declaration is rejected fail-closed."""
    if not name or name.casefold() in _RESERVED_NAMES:
        logger.info("review MCP skipped reserved or empty name: {}", name)
        return None
    if raw.get("oauth") or raw.get("auth") == "oauth":
        logger.info("review MCP {} rejected: OAuth remotes are out of scope", name)
        return None
    if raw.get("readOnly") is False or raw.get("read_only") is False:
        logger.info("review MCP {} rejected: write servers are not attached", name)
        return None
    tools_raw = raw.get("tools") or []
    tools = tuple(str(item) for item in tools_raw if isinstance(item, str) and item.strip())
    if any(_looks_like_write_tool(tool) for tool in tools):
        logger.info("review MCP {} rejected: tool allowlist includes a write verb", name)
        return None
    command = raw.get("command")
    url = raw.get("url")
    args_raw = raw.get("args") or []
    args = tuple(str(item) for item in args_raw if isinstance(item, str))
    if isinstance(command, str) and command.strip():
        return ConsumerMcpServer(
            name=name,
            command=command.strip(),
            args=args,
            url=None,
            tools=tools,
        )
    if isinstance(url, str) and url.startswith(
        ("http://127.0.0.1", "http://localhost", "https://")
    ):
        if "oauth" in url.casefold():
            logger.info("review MCP {} rejected: OAuth URL", name)
            return None
        return ConsumerMcpServer(name=name, command=None, args=(), url=url, tools=tools)
    logger.info("review MCP {} rejected: need local stdio command or http(s) URL", name)
    return None


def _servers_from_mapping(payload: dict[str, Any]) -> list[ConsumerMcpServer]:
    block = payload.get("mcpServers") or payload.get("servers") or {}
    if not isinstance(block, dict):
        return []
    servers: list[ConsumerMcpServer] = []
    for name, raw in block.items():
        if isinstance(name, str) and isinstance(raw, dict):
            parsed = validate_consumer_mcp_server(raw, name=name)
            if parsed is not None:
                servers.append(parsed)
    return servers


def load_consumer_mcp_servers(
    repo_root: Path,
    *,
    configured: list[dict[str, Any]] | None = None,
) -> list[ConsumerMcpServer]:
    """Load fail-closed read-only consumer MCP servers for a review."""
    servers: list[ConsumerMcpServer] = []
    seen: set[str] = set()
    for raw in configured or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "")
        parsed = validate_consumer_mcp_server(raw, name=name)
        if parsed is not None and parsed.name not in seen:
            servers.append(parsed)
            seen.add(parsed.name)
    for rel in _DISCOVERY_FILES:
        path = repo_root / rel
        if not path.is_file():
            continue
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.info("review MCP file {} ignored: {}", rel, exc)
            continue
        if isinstance(loaded, dict):
            for parsed in _servers_from_mapping(loaded):
                if parsed.name not in seen:
                    servers.append(parsed)
                    seen.add(parsed.name)
    return servers


def consumer_mcp_stdio_entries(servers: list[ConsumerMcpServer]) -> dict[str, dict[str, Any]]:
    """JSON ``mcpServers`` entries for stdio consumer servers (Claude/Gemini)."""
    entries: dict[str, dict[str, Any]] = {}
    for server in servers:
        if server.command:
            entries[server.name] = server.as_stdio_entry()
    return entries


__all__ = [
    "ConsumerMcpServer",
    "consumer_mcp_stdio_entries",
    "load_consumer_mcp_servers",
    "validate_consumer_mcp_server",
]
