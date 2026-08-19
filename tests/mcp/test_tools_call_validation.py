"""``tools/call`` validates arguments against ``input_schema`` (issue #267 / D14)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mergecraft.mcp.server import MCP_ENDPOINT, create_mcp_app
from mergecraft.mcp.shared import EMPTY_SCHEMA, ToolClass, ToolResult, ToolSpec

XFAIL_W22 = pytest.mark.xfail(
    reason="green after W22: tools/call validates arguments against input_schema",
    strict=False,
)

TOOL_NAME = "probe"
REQ_ID = 77

STRICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"ref": {"type": "string"}},
    "required": ["ref"],
    "additionalProperties": False,
}
PERMISSIVE_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}
UNUSABLE_SCHEMA: dict[str, Any] = {"type": "not-a-json-schema-type"}


class _Probe:
    """Tool double that records every argument mapping that reached ``execute``."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, arguments: Mapping[str, Any]) -> ToolResult:
        self.calls.append(dict(arguments))
        return ToolResult(content=[{"type": "text", "text": "executed"}])


CallTool = Callable[[Any], dict[str, Any]]


@pytest.fixture
def probe_tool() -> Callable[[dict[str, Any]], tuple[CallTool, _Probe]]:
    """Build a one-tool MCP app over ``schema`` and return (caller, probe)."""

    def _build(schema: dict[str, Any]) -> tuple[CallTool, _Probe]:
        probe = _Probe()
        spec = ToolSpec(
            name=TOOL_NAME,
            description="Probe tool for argument validation.",
            input_schema=schema,
            execute=probe.execute,
            tool_class=ToolClass.ANALYSIS,
        )
        client = TestClient(create_mcp_app([spec]))

        def _call(arguments: Any) -> dict[str, Any]:
            response = client.post(
                MCP_ENDPOINT,
                json={
                    "jsonrpc": "2.0",
                    "id": REQ_ID,
                    "method": "tools/call",
                    "params": {"name": TOOL_NAME, "arguments": arguments},
                },
            )
            assert response.status_code == 200
            body: dict[str, Any] = response.json()
            return body

        return _call, probe

    return _build


@XFAIL_W22
def test_missing_required_argument_is_rejected_before_execute(
    probe_tool: Callable[[dict[str, Any]], tuple[CallTool, _Probe]],
) -> None:
    """A call missing a required property never reaches the tool body."""
    call, probe = probe_tool(STRICT_SCHEMA)

    body = call({})

    assert probe.calls == []
    assert body["error"]["code"] == -32602


@XFAIL_W22
def test_extra_property_is_rejected_when_additional_properties_is_false(
    probe_tool: Callable[[dict[str, Any]], tuple[CallTool, _Probe]],
) -> None:
    """``additionalProperties: false`` is enforced by the server, not by the tool."""
    call, probe = probe_tool(STRICT_SCHEMA)

    body = call({"ref": "main", "unexpected": 1})

    assert probe.calls == []
    assert body["error"]["code"] == -32602


@XFAIL_W22
def test_wrongly_typed_argument_is_rejected_before_execute(
    probe_tool: Callable[[dict[str, Any]], tuple[CallTool, _Probe]],
) -> None:
    """A property of the wrong JSON type is invalid params, not a tool-level crash."""
    call, probe = probe_tool(STRICT_SCHEMA)

    body = call({"ref": 123})

    assert probe.calls == []
    assert body["error"]["code"] == -32602


@XFAIL_W22
def test_validation_failure_is_a_well_formed_jsonrpc_error(
    probe_tool: Callable[[dict[str, Any]], tuple[CallTool, _Probe]],
) -> None:
    """The rejection echoes the request id and carries an error object, not a result."""
    call, _probe = probe_tool(STRICT_SCHEMA)

    body = call({})

    assert body["jsonrpc"] == "2.0"
    assert body["id"] == REQ_ID
    assert "result" not in body
    error = body["error"]
    assert isinstance(error["code"], int)
    assert isinstance(error["message"], str)
    assert error["message"]


def test_valid_arguments_still_reach_execute(
    probe_tool: Callable[[dict[str, Any]], tuple[CallTool, _Probe]],
) -> None:
    """Validation must not stand between a schema-conforming call and the tool."""
    call, probe = probe_tool(STRICT_SCHEMA)

    body = call({"ref": "main"})

    assert "error" not in body
    assert body["result"]["content"][0]["text"] == "executed"
    assert probe.calls == [{"ref": "main"}]


def test_permissive_schema_accepts_arbitrary_arguments(
    probe_tool: Callable[[dict[str, Any]], tuple[CallTool, _Probe]],
) -> None:
    """A schema that declares no properties and no ban still admits everything."""
    call, probe = probe_tool(PERMISSIVE_SCHEMA)

    body = call({"anything": [1, 2], "else": "yes"})

    assert "error" not in body
    assert probe.calls == [{"anything": [1, 2], "else": "yes"}]


def test_empty_schema_tool_accepts_the_empty_argument_object(
    probe_tool: Callable[[dict[str, Any]], tuple[CallTool, _Probe]],
) -> None:
    """``EMPTY_SCHEMA`` tools (e.g. list_python_dependencies) take no arguments at all."""
    call, probe = probe_tool(EMPTY_SCHEMA)

    body = call({})

    assert "error" not in body
    assert probe.calls == [{}]


def test_unusable_schema_does_not_break_the_call(
    probe_tool: Callable[[dict[str, Any]], tuple[CallTool, _Probe]],
) -> None:
    """A tool schema the validator cannot use must not crash the endpoint.

    ``set_output`` accepts a consumer-supplied ``output_schema`` verbatim, so an
    invalid schema is reachable in production. Whether W22 then fails open (execute)
    or fails closed (``-32602``) is deliberately unpinned; only the non-crash,
    well-formed-response invariant is asserted here.
    """
    call, _probe = probe_tool(UNUSABLE_SCHEMA)

    body = call({"ref": "main"})

    assert body["id"] == REQ_ID
    assert ("result" in body) != ("error" in body)
