"""J1.1 — computed cost, honest None tokens, kill-switch (D10, G3)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.jev.support import (
    PINNED_MODEL,
    TRANSPORT_DIR,
    import_jev,
)


def _cost() -> Any:
    return import_jev("cost")


def _client() -> Any:
    return import_jev("client")


def test_price_table_is_keyed_by_pinned_model() -> None:
    cost = _cost()
    assert PINNED_MODEL in cost.PRICE_TABLE
    input_price, output_price = cost.PRICE_TABLE[PINNED_MODEL]
    assert input_price > 0
    assert output_price > 0


def test_compute_cost_uses_price_table_when_tokens_known() -> None:
    cost = _cost()
    assessment = cost.compute_cost(
        model=PINNED_MODEL,
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    input_price, output_price = cost.PRICE_TABLE[PINNED_MODEL]
    assert assessment.cost_known is True
    assert assessment.cost_usd == pytest.approx(input_price + output_price)
    assert assessment.cost_usd != 0


def test_unreported_tokens_set_cost_known_false_not_zero() -> None:
    cost = _cost()
    assessment = cost.compute_cost(
        model=PINNED_MODEL,
        input_tokens=None,
        output_tokens=None,
    )
    assert assessment.cost_known is False
    assert assessment.cost_usd is None


def test_partial_none_tokens_are_not_recorded_as_zero_cost() -> None:
    cost = _cost()
    assessment = cost.compute_cost(
        model=PINNED_MODEL,
        input_tokens=None,
        output_tokens=8,
    )
    assert assessment.cost_known is False
    assert assessment.cost_usd is None


def test_unknown_model_does_not_invent_zero_cost() -> None:
    cost = _cost()
    assessment = cost.compute_cost(
        model="jev-not-a-model",
        input_tokens=10,
        output_tokens=1,
    )
    assert assessment.cost_known is False
    assert assessment.cost_usd is None


async def test_client_survives_usage_input_tokens_none() -> None:
    module = _client()
    transport = module.RecordedTransport.from_fixture(TRANSPORT_DIR / "usage_tokens_none.json")
    client = module.AsyncJevClient(api_key="mc-test-jev-key", transport=transport)
    result = await client.call(state={"hunk": "x"}, pack_id="unit/v1", unit_id="u")
    assert result.skipped is False
    assert result.cost_known is False
    assert result.cost_usd is None
    assert result.response.usage.input_tokens is None
    assert result.response.usage.output_tokens is None


def test_token_budget_kill_switch_records_stop() -> None:
    cost = _cost()
    budget = cost.TokenBudget(max_tokens=50)
    accepted = budget.record_usage(input_tokens=40, output_tokens=5)
    assert accepted is True
    assert budget.stopped is False
    rejected = budget.record_usage(input_tokens=20, output_tokens=0)
    assert rejected is False
    assert budget.stopped is True
    assert budget.stop_reason == "budget"
    assert budget.should_stop() is True


def test_token_budget_none_usage_does_not_count_as_zero() -> None:
    cost = _cost()
    budget = cost.TokenBudget(max_tokens=50)
    accepted = budget.record_usage(input_tokens=None, output_tokens=None)
    assert accepted is True
    assert budget.tokens_used == 0
    assert budget.cost_known is False
    assert budget.stopped is False
