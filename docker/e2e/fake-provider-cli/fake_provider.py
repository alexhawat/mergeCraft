#!/usr/bin/env python3
"""A deterministic Claude client that performs real review MCP calls."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

REQUIRED_TOOLS = {
    "select_mode",
    "checkout_pr",
    "git",
    "run_analyzers",
    "submit_review_verdict",
    "set_output",
}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "outcome": {"type": "string", "enum": ["passed"]},
        "head_sha": {"type": "string"},
        "terminal_id": {"type": "string"},
        "read_path": {"type": "string"},
    },
    "required": ["outcome", "head_sha", "terminal_id", "read_path"],
    "additionalProperties": False,
}


def review(config_path: Path) -> dict[str, Any]:
    config = json.loads(config_path.read_text())
    entries = config["mcpServers"].values()
    entry = next(row for row in entries if row.get("url", "").endswith("/mcp/reviewer"))
    url = entry["url"]
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("the E2E client only calls the local MCP server")
    headers = {**entry.get("headers", {}), "Content-Type": "application/json"}
    if not headers.get("Authorization"):
        raise RuntimeError("MCP bearer header missing")
    sequence = 0

    def rpc(method: str, params: dict[str, Any]) -> dict[str, Any]:
        nonlocal sequence
        sequence += 1
        request = Request(
            url,
            data=json.dumps(
                {"jsonrpc": "2.0", "id": sequence, "method": method, "params": params}
            ).encode(),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=60) as response:
            message = json.load(response)
        if message.get("error") or message.get("id") != sequence:
            raise RuntimeError(f"MCP {method} failed: {message.get('error')}")
        result: dict[str, Any] = message["result"]
        if result.get("isError"):
            raise RuntimeError(f"MCP {params.get('name', method)} refused: {result['content']}")
        return result

    def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = rpc("tools/call", {"name": name, "arguments": arguments})
        content: dict[str, Any] = json.loads(
            next(block["text"] for block in result["content"] if block["type"] == "text")
        )
        return content

    rpc(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mergecraft-e2e", "version": "1"},
        },
    )
    available = {tool["name"] for tool in rpc("tools/list", {})["tools"]}
    if not available >= REQUIRED_TOOLS:
        raise RuntimeError(f"review protocol tools missing: {sorted(REQUIRED_TOOLS - available)}")
    call("select_mode", {"mode": "Review", "issue_number": 42})
    checkout = call("checkout_pr", {"pull_number": 42})
    if checkout.get("scope") == "api-only" or checkout.get("degraded"):
        raise RuntimeError("fixture checkout must provide the full local diff")
    read = call("git", {"command": "show", "args": ["HEAD:README.md"]})
    if "Fixture update validated through MCP." not in read["output"]:
        raise RuntimeError("MCP file read did not return the fixture head")
    analyzed = call(
        "run_analyzers", {"changed_files": ["README.md"], "diff_path": checkout["diffPath"]}
    )
    if not analyzed["ran"] or not any(
        row["id"] == "self-silencing" and row["status"] == "passed" for row in analyzed["analyzers"]
    ):
        raise RuntimeError("native analyzer did not execute successfully")
    terminal = call(
        "submit_review_verdict",
        {
            "verdict": "approve",
            "summary": "Read the fixture diff and README through MCP; native analysis passed.",
            "findings": [],
        },
    )
    if terminal.get("recorded") is not True or terminal.get("verdict") != "approve":
        raise RuntimeError("terminal verdict was not accepted")
    output = {
        "outcome": "passed",
        "head_sha": checkout["headSha"],
        "terminal_id": terminal["id"],
        "read_path": "README.md",
    }
    call("set_output", output)
    return output


def main() -> None:
    if "--version" in sys.argv:
        print("claude-e2e 1.0")
        return
    config = Path(sys.argv[sys.argv.index("--mcp-config") + 1])
    output = review(config)
    print(
        json.dumps(
            {
                "type": "result",
                "result": json.dumps(output),
                "usage": {"input_tokens": 12, "output_tokens": 8},
                "total_cost_usd": 0.0,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
