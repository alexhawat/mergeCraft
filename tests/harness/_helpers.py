"""Shared helpers for RH1 RED tests — imports stay lazy in callers."""

from __future__ import annotations

from typing import Any


def snapshot(**overrides: Any) -> dict[str, Any]:
    """Minimal request snapshot passed to ``match_fixture`` (RH1.2 contract)."""
    base: dict[str, Any] = {
        "provider": "default",
        "model": "dummy",
        "mode": "review",
        "streaming": False,
        "turn_index": 0,
        "has_tool_results": None,
        "test_context_id": None,
        "body": {"messages": [{"role": "user", "content": "review this diff"}]},
    }
    base.update(overrides)
    return base
