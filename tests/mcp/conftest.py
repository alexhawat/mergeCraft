"""MCP test fixtures — reset process-global state between tests (#421 / D4)."""

from __future__ import annotations

import pytest

from mergecraft.mcp.shared import reset_mcp_process_state


@pytest.fixture(autouse=True)
def _reset_mcp_process_state_between_tests() -> None:
    reset_mcp_process_state()
    yield
    reset_mcp_process_state()
