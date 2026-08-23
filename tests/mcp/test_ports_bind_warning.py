"""MERGECRAFT_MCP_PORT busy fallback warns before binding port 0."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import mergecraft.mcp.ports as ports_mod
from mergecraft.mcp.ports import resolve_uvicorn_bind_port

if TYPE_CHECKING:
    import pytest


def test_resolve_uvicorn_bind_port_warns_when_requested_port_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MERGECRAFT_MCP_PORT", "41234")
    monkeypatch.setattr(ports_mod, "port_available", lambda _port: False)

    with patch.object(ports_mod.logger, "warning") as warning:
        assert resolve_uvicorn_bind_port() == 0

    warning.assert_called_once()
    assert warning.call_args.args[0].startswith("MERGECRAFT_MCP_PORT={} is busy")
    assert warning.call_args.args[1] == 41234
