"""Shared path scope constants for the anti-slop analyzer (#393)."""

from __future__ import annotations

from typing import Final

ANTISLOP_SCOPED_SUFFIXES: Final[tuple[str, ...]] = (
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
)

ANTISLOP_JS_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}
)

__all__ = ["ANTISLOP_JS_SUFFIXES", "ANTISLOP_SCOPED_SUFFIXES"]
