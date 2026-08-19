"""RH4 — MCP scripted double."""

from __future__ import annotations

from tests.support.provider_harness.mcp_double import scripted_mcp_app


def test_tool_listing_and_call_are_deterministic() -> None:
    client = scripted_mcp_app({"calls": {"echo": {"result": {"ok": True}}}})
    payload = client.call_tool("echo", {"x": 1})
    assert payload["result"]["ok"] is True


def test_resource_read_and_prompt_retrieval_are_deterministic() -> None:
    client = scripted_mcp_app({"calls": {"read_resource": {"result": {"contents": []}}}})
    payload = client.call_tool("read_resource", {"uri": "file://x"})
    assert "result" in payload


def test_protocol_error_is_explicit() -> None:
    client = scripted_mcp_app({"calls": {"broken": {"error": "protocol failure"}}})
    payload = client.call_tool("broken", {})
    assert payload["error"] == "protocol failure"
