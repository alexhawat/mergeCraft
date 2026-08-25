"""Leaf JSON-RPC error types — no imports from sibling MCP modules."""

from __future__ import annotations

from typing import Any, NamedTuple


class RpcError(NamedTuple):
    """A JSON-RPC error code/message pair, before it is wrapped in an envelope."""

    code: int
    message: str


PARSE_ERROR = RpcError(-32700, "Parse error")


def json_rpc_parse_error(*, include_id: bool, req_id: Any = None) -> dict[str, Any]:
    """Build a parse-error envelope.

    HTTP transport omits ``id`` when the body cannot be parsed; stdio sets
    ``id`` to ``None`` so clients always receive a well-formed response object.
    """
    envelope: dict[str, Any] = {
        "jsonrpc": "2.0",
        "error": {"code": PARSE_ERROR.code, "message": PARSE_ERROR.message},
    }
    if include_id:
        envelope["id"] = req_id
    return envelope


def rpc_error(req_id: Any, error: RpcError) -> dict[str, Any]:
    """Wrap ``error`` in the JSON-RPC response envelope for ``req_id``."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": error.code, "message": error.message},
    }


__all__ = ["PARSE_ERROR", "RpcError", "json_rpc_parse_error", "rpc_error"]
