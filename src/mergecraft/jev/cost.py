"""Local Jev price table, per-run token budget, and kill-switch (D10).

TypeSafe's Usage type reports tokens and no cost (T4 / G3). Cost is computed
here from a table keyed by the pinned model id. Unreported tokens record
``cost_known: false`` rather than a silent zero.

Exports:
    PRICE_TABLE: USD per million tokens, keyed by pinned model id.
    CostAssessment: Computed cost or an honest unknown.
    TokenBudget: Per-run token cap and kill-switch state.
    compute_cost: Price a call without inventing zero for ``None`` tokens.
"""

from __future__ import annotations

import threading
from typing import Final

from pydantic import BaseModel, ConfigDict

from mergecraft.jev.types import PINNED_MODEL

# Public TypeSafe pricing as of 2026-09-17: $0.042 per million input tokens
# (docs.typesafe.ai/models). Output is documented as free; the J2 contract
# requires both sides of the table to be positive so a missing output rate
# cannot collapse to a silent zero. The published Mtok rate is used for both.
_USD_PER_MTOK: Final[float] = 0.042

PRICE_TABLE: Final[dict[str, tuple[float, float]]] = {
    PINNED_MODEL: (_USD_PER_MTOK, _USD_PER_MTOK),
}

_MTOK: Final[float] = 1_000_000.0


class CostAssessment(BaseModel):
    """Computed USD cost, or an honest unknown when tokens or price are missing."""

    model_config = ConfigDict(extra="forbid")

    cost_known: bool
    cost_usd: float | None


class TokenBudget:
    """Per-run token cap. Crossing it stops further dispatch and records why.

    ``record_usage`` is safe for concurrent callers that share one budget
    (same API key / same client).
    """

    def __init__(self, max_tokens: int) -> None:
        self.max_tokens = max_tokens
        self.tokens_used = 0
        self.stopped = False
        self.stop_reason: str | None = None
        self.cost_known = True
        self._lock = threading.Lock()

    def should_stop(self) -> bool:
        """Return whether the kill-switch has already fired."""
        with self._lock:
            return self.stopped

    def record_usage(self, *, input_tokens: int | None, output_tokens: int | None) -> bool:
        """Account one call's tokens.

        Args:
            input_tokens: Prompt tokens, or ``None`` when the API omitted them.
            output_tokens: Completion tokens, or ``None`` when omitted.

        Returns:
            bool: ``True`` when the usage was accepted (or was unreported).
            ``False`` when the increment would exceed the cap; the stop is
            recorded and ``tokens_used`` is left unchanged.
        """
        with self._lock:
            if input_tokens is None or output_tokens is None:
                self.cost_known = False
                return True
            if self.stopped:
                return False
            increment = input_tokens + output_tokens
            if self.tokens_used + increment > self.max_tokens:
                self.stopped = True
                self.stop_reason = "budget"
                return False
            self.tokens_used += increment
            return True


def compute_cost(
    *,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> CostAssessment:
    """Price a call from the local table.

    Args:
        model: Model id the call ran against.
        input_tokens: Prompt tokens, or ``None`` when unreported.
        output_tokens: Completion tokens, or ``None`` when unreported.

    Returns:
        CostAssessment: Known USD cost, or ``cost_known=False`` / ``cost_usd=None``
        when either token count is missing or the model is not in the table.
    """
    if input_tokens is None or output_tokens is None:
        return CostAssessment(cost_known=False, cost_usd=None)
    prices = PRICE_TABLE.get(model)
    if prices is None:
        return CostAssessment(cost_known=False, cost_usd=None)
    input_price, output_price = prices
    cost_usd = (input_price * input_tokens / _MTOK) + (output_price * output_tokens / _MTOK)
    return CostAssessment(cost_known=True, cost_usd=cost_usd)


__all__ = [
    "PRICE_TABLE",
    "CostAssessment",
    "TokenBudget",
    "compute_cost",
]
