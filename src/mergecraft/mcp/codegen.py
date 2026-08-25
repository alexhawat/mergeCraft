"""Codegen helpers — minimal :class:`ToolContext` for static MCP artifact generation."""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from typing import TYPE_CHECKING

from mergecraft.mcp.context_factory import minimal_tool_context

if TYPE_CHECKING:
    from collections.abc import Iterator

    from mergecraft.mcp.context import ToolContext


@contextmanager
def codegen_tool_context() -> Iterator[ToolContext]:
    """Yield a minimal :class:`ToolContext` with an auto-cleaned temp workspace."""
    with tempfile.TemporaryDirectory(prefix="mergecraft-gen-mcp-") as tmpdir:
        yield minimal_tool_context(tmpdir)


__all__ = ["codegen_tool_context"]
