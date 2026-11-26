"""One scripted two-attempt model chain, run on both review entry points (#1586).

Each attempt either streams its usage step by step (and reports the same total
when it finishes) or reports it only once, as an aggregate, when it finishes. An
attempt that reports no ``cost_usd`` is priced by the catalog at the model it
actually ran. The Action (``tests/action/test_primary_stream_charges.py``) and
the offline review (``tests/review/test_offline_model_chain.py``) both run these
scripts and must account for them identically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mergecraft.agents import curated_model_catalog
from mergecraft.agents.shared import AgentResult, AgentUsage
from mergecraft.agents.stream_budget import charge_review_stream_step

if TYPE_CHECKING:
    import pytest

_MTOK = 1_000_000.0


@dataclass(frozen=True, slots=True)
class ScriptedAttempt:
    """How one chain attempt spends and ends."""

    streamed: bool
    success: bool
    input_tokens: int
    output_tokens: int
    cost_usd: float | None = None
    retryable: bool = True

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def usage(self) -> AgentUsage:
        return AgentUsage(
            agent="claude",
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cost_usd=self.cost_usd,
        )

    def result(self) -> AgentResult:
        if self.success:
            return AgentResult(success=True, terminal_submission_received=True, usage=self.usage())
        return AgentResult(
            success=False,
            error="scripted provider failure",
            metadata={"retryable": self.retryable},
            usage=self.usage(),
        )

    def run(self, ctx: Any) -> AgentResult:
        """Spend like the scripted attempt: stream first when it streams, then finish."""
        reason = (
            charge_review_stream_step(
                {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens},
                budget_tracker=ctx.budget_tracker,
                provider_budget=None,
                stream_charges=ctx.stream_charges,
                cost_usd=self.cost_usd,
            )
            if self.streamed
            else None
        )
        assert reason is None
        return self.result()


_AGGREGATE_FAILS = ScriptedAttempt(
    streamed=False, success=False, input_tokens=50_000, output_tokens=5_000
)
_STREAM_FAILS = ScriptedAttempt(
    streamed=True, success=False, input_tokens=120_000, output_tokens=0, cost_usd=1.0
)

CHAIN_SCRIPTS: dict[str, tuple[ScriptedAttempt, ScriptedAttempt]] = {
    "aggregate-fails-then-stream-wins": (
        _AGGREGATE_FAILS,
        ScriptedAttempt(
            streamed=True, success=True, input_tokens=120_000, output_tokens=0, cost_usd=1.0
        ),
    ),
    "stream-fails-then-aggregate-wins": (
        _STREAM_FAILS,
        ScriptedAttempt(streamed=False, success=True, input_tokens=40_000, output_tokens=4_000),
    ),
    "every-attempt-fails": (
        _AGGREGATE_FAILS,
        ScriptedAttempt(
            streamed=True,
            success=False,
            input_tokens=120_000,
            output_tokens=0,
            cost_usd=1.0,
            retryable=False,
        ),
    ),
}

#: USD per million (input, output) tokens: the two chain models price differently.
_RATES: tuple[tuple[float, float], tuple[float, float]] = ((2.0, 8.0), (1.0, 4.0))


def expected_cost(attempt: ScriptedAttempt, *, position: int) -> float:
    """The attempt's cost: its own report, else its model's catalog rate."""
    if attempt.cost_usd is not None:
        return attempt.cost_usd
    rate_in, rate_out = _RATES[position]
    return (attempt.input_tokens * rate_in + attempt.output_tokens * rate_out) / _MTOK


def install_chain_rates(monkeypatch: pytest.MonkeyPatch, models: tuple[str, str]) -> None:
    """Give the chain's two models distinct catalog rates (``_RATES``)."""
    rates = dict(zip(models, _RATES, strict=True))

    def _price(
        *,
        model: str | None,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int | None = None,
    ) -> float | None:
        del cache_read_tokens
        if model not in rates:
            return None
        rate_in, rate_out = rates[model]
        return (input_tokens * rate_in + output_tokens * rate_out) / _MTOK

    monkeypatch.setattr(curated_model_catalog, "compute_review_cost_usd", _price)


__all__ = [
    "CHAIN_SCRIPTS",
    "ScriptedAttempt",
    "expected_cost",
    "install_chain_rates",
]
