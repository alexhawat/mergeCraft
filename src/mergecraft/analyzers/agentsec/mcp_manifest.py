"""Detect and parse MCP server manifest files for agent-security scanning."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import yaml

from mergecraft.analyzers.agentsec.policy import ManifestDocument

if TYPE_CHECKING:
    from pathlib import Path

_MCP_JSON_NAMES = frozenset({".mcp.json"})
_MCP_CONFIG_NAMES = frozenset({"claude_desktop_config.json"})
_MCP_SERVER_SUFFIXES = (".yaml", ".yml", ".json")


def discover_mcp_documents(
    *,
    repo_root: Path,
    changed_files: list[str],
) -> list[ManifestDocument]:
    """Return MCP manifest documents among ``changed_files``."""
    documents: list[ManifestDocument] = []
    for rel in changed_files:
        path = repo_root / rel
        if not path.is_file():
            continue
        parsed = parse_mcp_file(path, repo_relative=rel)
        if parsed is not None:
            documents.append(parsed)
    return documents


def parse_mcp_file(path: Path, *, repo_relative: str | None = None) -> ManifestDocument | None:
    """Parse one MCP manifest path into a :class:`ManifestDocument`."""
    rel = repo_relative or path.name
    name = path.name.casefold()

    if name in _MCP_JSON_NAMES or name.endswith(".mcp.json"):
        return _parse_mcp_json(path, rel=rel)
    if name in _MCP_CONFIG_NAMES:
        return _parse_claude_desktop_config(path, rel=rel)
    if "/mcp-servers/" in rel.replace("\\", "/") and name.endswith(_MCP_SERVER_SUFFIXES):
        return _parse_mergecraft_mcp_server(path, rel=rel)
    if path.suffix.casefold() == ".json":
        return _parse_json_mcp_servers(path, rel=rel)
    return None


def _parse_mcp_json(path: Path, *, rel: str) -> ManifestDocument | None:
    data = _load_json(path)
    if data is None:
        return None
    return _document_from_mapping(data, rel=rel, base_line=1)


def _parse_claude_desktop_config(path: Path, *, rel: str) -> ManifestDocument | None:
    data = _load_json(path)
    if not isinstance(data, dict):
        return None
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return None
    return _document_from_mcp_servers(servers, rel=rel)


def _parse_json_mcp_servers(path: Path, *, rel: str) -> ManifestDocument | None:
    data = _load_json(path)
    if not isinstance(data, dict):
        return None
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return None
    return _document_from_mcp_servers(servers, rel=rel)


def _parse_mergecraft_mcp_server(path: Path, *, rel: str) -> ManifestDocument | None:
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return _document_from_mapping(data, rel=rel, base_line=1, raw_text=text)


def _document_from_mcp_servers(servers: dict[str, Any], *, rel: str) -> ManifestDocument:
    fields: dict[str, str] = {}
    field_lines: dict[str, int] = {}
    for index, (server_name, entry) in enumerate(sorted(servers.items())):
        if not isinstance(entry, dict):
            continue
        prefix = f"server:{server_name}"
        for key, value in entry.items():
            field_name = f"{prefix}.{key}"
            fields[field_name] = _stringify(value)
            field_lines[field_name] = index + 1
    return ManifestDocument(kind="mcp", path=rel, fields=fields, field_lines=field_lines)


def _document_from_mapping(
    data: dict[str, Any],
    *,
    rel: str,
    base_line: int,
    raw_text: str | None = None,
) -> ManifestDocument:
    fields: dict[str, str] = {}
    field_lines: dict[str, int] = {}
    for key, value in data.items():
        field_name = str(key)
        fields[field_name] = _stringify(value)
        field_lines[field_name] = _line_for_key(raw_text, field_name, default=base_line)
    if "args" in data and "command" in data:
        command = _stringify(data.get("command"))
        args = _stringify(data.get("args"))
        fields["command_line"] = f"{command} {args}".strip()
        field_lines["command_line"] = field_lines.get("command", base_line)
    return ManifestDocument(kind="mcp", path=rel, fields=fields, field_lines=field_lines)


def _line_for_key(raw_text: str | None, key: str, *, default: int) -> int:
    if raw_text is None:
        return default
    for index, line in enumerate(raw_text.splitlines(), start=1):
        if line.strip().startswith(f"{key}:"):
            return index
    return default


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_stringify(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return None


__all__ = ["discover_mcp_documents", "parse_mcp_file"]
