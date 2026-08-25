"""Leaf JSON-RPC error types — no imports from sibling MCP modules."""

from __future__ import annotations

from typing import Any, NamedTuple


class RpcError(NamedTuple):
    """A JSON-RPC error code/message pair, before it is wrapped in an envelope."""

    code: int
    message: str


def rpc_error(req_id: Any, error: RpcError) -> dict[str, Any]:
    """Wrap ``error`` in the JSON-RPC response envelope for ``req_id``."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": error.code, "message": error.message},
    }


__all__ = ["RpcError", "rpc_error"]
