"""Shared token bookkeeping for provider stream handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping


def sync_open_pair_bookkeeping(
    bookkeeping: dict[str, dict[str, Any]],
    usage: Mapping[str, Any],
    *,
    active_key: str | None = None,
) -> None:
    """Stamp the active provider/LLM pair with usage totals from a turn event."""
    tokens_in = int(usage.get("input_tokens") or usage.get("inputTokens") or 0)
    tokens_out = int(usage.get("output_tokens") or usage.get("outputTokens") or 0)
    totals = {"tokens_in": tokens_in, "tokens_out": tokens_out}
    key = active_key
    if key is None and len(bookkeeping) == 1:
        key = next(iter(bookkeeping))
    if key is None or key not in bookkeeping:
        return
    bookkeeping[key] = dict(totals)
