"""Published OpenCode Go usage-value estimates for missing step costs.

Module: mergecraft.agents.opencode_pricing
Depends: datetime, math

Exports:
    Functions:
        estimate_go_step_cost — Price disjoint DeepSeek step counters in USD.

Rates and weekday UTC schedule verified on 2026-11-01:
https://opencode.ai/v2/docs/console/go/#usage-limits
These are subscription usage values, not incremental subscription charges.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

# Input, cached read, output: USD per million tokens, off-peak. Keep this
# separate from the curated generation catalog: pricing must not impose
# Ultramarine's output cap, reasoning defaults, or harness restrictions.
_GO_RATES = {
    "opencode-go/deepseek-v4.1-flash": (0.15, 0.003, 0.60),
    "opencode-go/deepseek-v4-pro": (0.66, 0.022, 1.98),
}
GO_COST_NOTE = "includes OpenCode Go usage value; subscription billed separately"
GO_ESTIMATED_COST_NOTE = (
    "includes estimated OpenCode Go usage value; subscription billed separately"
)


def estimate_go_step_cost(
    *,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    timestamp_ms: object,
) -> float | None:
    """Estimate one step using its completion timestamp and Go's public rates.

    Args:
        model (str | None): Fully qualified provider/model; no cross-provider aliases.
        input_tokens (int): Uncached input, disjoint from cache counters.
        output_tokens (int): Completion tokens including reasoning.
        cache_read_tokens (int): Cached prompt tokens.
        cache_write_tokens (int): Must be zero; these models publish no write rate.
        timestamp_ms (object): CLI event's Unix milliseconds. Missing/invalid
            timestamps leave cost unknown rather than price a replay at today's rate.

    Returns:
        float | None: Estimated usage value, or None for unavailable pricing.

    Examples:
        >>> estimate_go_step_cost(model="opencode-go/deepseek-v4.1-flash",
        ...     input_tokens=1_000_000, output_tokens=1_000_000,
        ...     cache_read_tokens=1_000_000, cache_write_tokens=0,
        ...     timestamp_ms=1793491200000)  # Sunday 2026-11-01 UTC
        0.753
    """
    rates = _GO_RATES.get(model or "")
    if rates is None or cache_write_tokens != 0:
        return None
    if min(input_tokens, output_tokens, cache_read_tokens) < 0:
        return None
    if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, (int, float)):
        return None
    if not math.isfinite(timestamp_ms):
        return None
    try:
        at = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
    except (ValueError, OverflowError, OSError):
        return None
    peak = at.weekday() < 5 and (1 <= at.hour < 4 or 6 <= at.hour < 10)
    multiplier = 2 if peak else 1
    input_rate, cache_rate, output_rate = rates
    return (
        multiplier
        * (input_tokens * input_rate + cache_read_tokens * cache_rate + output_tokens * output_rate)
        / 1_000_000
    )
