"""Shared token bookkeeping for provider stream handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping


def _usage_int(value: object) -> int:
    """Parse a usage counter defensively — non-numeric values default to 0."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return 0
        try:
            return int(stripped)
        except ValueError:
            return 0
    return 0


def sync_open_pair_bookkeeping(
    bookkeeping: dict[str, dict[str, Any]],
    usage: Mapping[str, Any],
    *,
    active_key: str | None = None,
) -> None:
    """Stamp the active provider/LLM pair with usage totals from a turn event."""
    tokens_in = _usage_int(usage.get("input_tokens") or usage.get("inputTokens"))
    tokens_out = _usage_int(usage.get("output_tokens") or usage.get("outputTokens"))
    totals = {"tokens_in": tokens_in, "tokens_out": tokens_out}
    key = active_key
    if key is None and len(bookkeeping) == 1:
        key = next(iter(bookkeeping))
    if key is None and len(bookkeeping) > 1:
        key = next(reversed(bookkeeping))
    if key is None or key not in bookkeeping:
        return
    bookkeeping[key] = dict(totals)
