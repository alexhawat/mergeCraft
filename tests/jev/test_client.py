"""J1.1 — pinned client, retry, TypeSafeAPIError, skips (G1-G3, D4, D8, D10)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tests.jev.support import (
    PINNED_MODEL,
    SKIP_REASONS,
    TEST_API_KEY,
    TRANSPORT_DIR,
    import_jev,
    load_transport_payload,
)


def _client_mod() -> Any:
    return import_jev("client")


def _recorded_client(
    fixture_name: str,
    *,
    api_key: str | None = TEST_API_KEY,
    **kwargs: Any,
) -> Any:
    module = _client_mod()
    transport = module.RecordedTransport.from_fixture(TRANSPORT_DIR / fixture_name)
    return module.AsyncJevClient(api_key=api_key, transport=transport, **kwargs)


def test_pinned_model_is_jev_1_13_0() -> None:
    client_mod = _client_mod()
    package = import_jev()
    assert client_mod.PINNED_MODEL == PINNED_MODEL
    assert package.PINNED_MODEL == PINNED_MODEL
    assert client_mod.PINNED_MODEL != "jev-latest"
    assert client_mod.PINNED_MODEL != "jev-preview"


async def test_call_sends_pinned_model_to_recorded_transport() -> None:
    client = _recorded_client("unit_happy.json")
    result = await client.call(
        state={"hunk": "wrap_agent_command"},
        pack_id="unit/v1",
        unit_id="unit-1",
        trust_tier="trusted",
    )
    assert result.skipped is False
    assert result.available is True
    assert result.incomplete is False
    assert result.model == PINNED_MODEL
    assert result.response.model == PINNED_MODEL
    assert client.transport.last_model == PINNED_MODEL


async def test_retry_on_transient_then_success() -> None:
    module = _client_mod()
    transport = module.FlakyRecordedTransport(
        failures=load_transport_payload("typesafe_500.json"),
        success=TRANSPORT_DIR / "unit_happy.json",
        fail_times=2,
    )
    client = module.AsyncJevClient(api_key=TEST_API_KEY, transport=transport)
    result = await client.call(state={"hunk": "x"}, pack_id="unit/v1", unit_id="u")
    assert result.skipped is False
    assert transport.calls == 3
    assert result.response.request_id == "req_unit_happy"


async def test_permanent_typesafe_error_does_not_retry() -> None:
    module = _client_mod()
    transport = module.FlakyRecordedTransport(
        failures=load_transport_payload("typesafe_400.json"),
        success=TRANSPORT_DIR / "unit_happy.json",
        fail_times=5,
    )
    client = module.AsyncJevClient(api_key=TEST_API_KEY, transport=transport)
    with pytest.raises(module.TypeSafeAPIError) as exc_info:
        await client.call(state={"hunk": "x"}, pack_id="unit/v1", unit_id="u")
    err = exc_info.value
    assert err.status_code == 400
    assert err.code == "invalid_request"
    assert transport.calls == 1
    mapped = module.map_typesafe_error(err)
    from mergecraft.utils.provider_failure import ProviderFailureClass

    assert mapped is ProviderFailureClass.PERMANENT


async def test_rate_limit_maps_to_retryable_provider_failure() -> None:
    module = _client_mod()
    transport = module.FlakyRecordedTransport(
        failures=load_transport_payload("typesafe_429.json"),
        success=TRANSPORT_DIR / "unit_happy.json",
        fail_times=5,
    )
    client = module.AsyncJevClient(api_key=TEST_API_KEY, transport=transport)
    with pytest.raises(module.TypeSafeAPIError) as exc_info:
        await client.call(state={"hunk": "x"}, pack_id="unit/v1", unit_id="u")
    mapped = module.map_typesafe_error(exc_info.value)
    from mergecraft.utils.provider_failure import ProviderFailureClass

    assert mapped is ProviderFailureClass.RETRYABLE
    assert exc_info.value.status_code == 429
    assert exc_info.value.code == "rate_limited"


def test_adapt_sdk_error_wraps_statusless_connection() -> None:
    """Status-less SDK/transport exceptions become TypeSafeAPIError, not a re-raise."""
    module = _client_mod()
    adapted = module._adapt_sdk_error(ConnectionError("dns"))
    assert isinstance(adapted, module.TypeSafeAPIError)
    assert adapted.code == "transport_error"
    assert adapted.status_code == 0


async def test_none_state_raises_structured_jev_error() -> None:
    module = _client_mod()
    client = _recorded_client("unit_happy.json")
    with pytest.raises(module.JevError) as exc_info:
        await client.call(state=None, pack_id="unit/v1", unit_id="u")
    assert exc_info.value.code == "invalid_state"


async def test_disabled_settings_are_a_recorded_skip_not_a_failure() -> None:
    from mergecraft.config.settings import JevSettings

    settings = JevSettings(enabled=False, model=PINNED_MODEL)
    client = _recorded_client("unit_happy.json", settings=settings)
    result = await client.call(state={"hunk": "x"}, pack_id="unit/v1", unit_id="u")
    assert result.skipped is True
    assert result.available is False
    assert result.incomplete is False
    assert result.reason == "disabled"
    assert result.reason in SKIP_REASONS
    assert client.transport.calls == 0


async def test_disabled_pack_is_a_recorded_skip_not_a_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-PACKS-DEAD: ``JevSettings.packs`` is applied on ``call``; a disabled pack is not sent."""
    from mergecraft.config.settings import JevSettings, default_settings

    packs = {pack_id: True for pack_id in default_settings().jev.packs}
    packs["unit/v1"] = False
    settings = JevSettings(enabled=True, model=PINNED_MODEL, packs=packs)
    monkeypatch.setattr(
        "mergecraft.config.settings.default_settings",
        lambda: default_settings().model_copy(update={"jev": settings}),
    )
    client = _recorded_client("unit_happy.json", settings=settings)
    result = await client.call(state={"hunk": "x"}, pack_id="unit/v1", unit_id="u")
    assert result.skipped is True
    assert result.available is False
    assert client.transport.calls == 0


async def test_enabled_without_credential_is_recorded_skip_not_silent_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    from mergecraft.config.settings import JevSettings

    settings = JevSettings(enabled=True, model=PINNED_MODEL)
    client = _recorded_client("unit_happy.json", api_key=None, settings=settings)
    result = await client.call(state={"hunk": "x"}, pack_id="unit/v1", unit_id="u")
    assert result.skipped is True
    assert result.available is False
    assert result.incomplete is False
    assert result.reason == "credential_absent"
    assert result.reason in SKIP_REASONS
    assert client.transport.calls == 0


async def test_kill_switch_stops_dispatch_and_records_the_stop() -> None:
    cost_mod = import_jev("cost")
    budget = cost_mod.TokenBudget(max_tokens=1)
    client = _recorded_client("unit_happy.json", budget=budget)
    first = await client.call(state={"hunk": "a"}, pack_id="unit/v1", unit_id="a")
    second = await client.call(state={"hunk": "b"}, pack_id="unit/v1", unit_id="b")
    assert first.skipped is False
    assert second.skipped is True
    assert second.reason == "kill_switch"
    assert second.available is False
    assert budget.stopped is True
    assert budget.stop_reason == "budget"
    assert client.transport.calls == 1


async def test_client_constructed_unbound_uses_later_bound_run_budget() -> None:
    """The shared per-run cap includes Jev when the client is built before bind."""
    from mergecraft.agents.token_budget import bind_run_budget

    cost_mod = import_jev("cost")
    bound = cost_mod.TokenBudget(max_tokens=10_000)
    client = _recorded_client("unit_happy.json")
    with bind_run_budget(bound):
        result = await client.call(state={"hunk": "a"}, pack_id="unit/v1", unit_id="a")
    assert result.skipped is False
    used = result.response.usage.input_tokens + result.response.usage.output_tokens
    assert bound.tokens_used == used
    assert bound.tokens_used <= bound.max_tokens


async def test_explicit_budget_wins_over_bound_run_budget() -> None:
    """Constructor ``budget=`` stays the cap even when a run budget is bound."""
    from mergecraft.agents.token_budget import bind_run_budget

    cost_mod = import_jev("cost")
    explicit = cost_mod.TokenBudget(max_tokens=10_000)
    bound = cost_mod.TokenBudget(max_tokens=10_000)
    client = _recorded_client("unit_happy.json", budget=explicit)
    with bind_run_budget(bound):
        result = await client.call(state={"hunk": "a"}, pack_id="unit/v1", unit_id="a")
    assert result.skipped is False
    assert explicit.tokens_used > 0
    assert bound.tokens_used == 0


async def test_concurrent_same_api_key_shares_one_budget() -> None:
    cost_mod = import_jev("cost")
    budget = cost_mod.TokenBudget(max_tokens=10_000)
    client = _recorded_client("unit_happy.json", budget=budget)
    first, second = await asyncio.gather(
        client.call(state={"hunk": "a"}, pack_id="unit/v1", unit_id="a"),
        client.call(state={"hunk": "b"}, pack_id="unit/v1", unit_id="b"),
    )
    assert first.skipped is False
    assert second.skipped is False
    assert client.transport.calls == 2
    used = first.response.usage.input_tokens + second.response.usage.input_tokens
    used += first.response.usage.output_tokens + second.response.usage.output_tokens
    assert budget.tokens_used == used
    assert budget.tokens_used <= budget.max_tokens


async def test_successful_call_records_non_negative_wall_clock_latency() -> None:
    client = _recorded_client("unit_happy.json")
    result = await client.call(state={"hunk": "x"}, pack_id="unit/v1", unit_id="u")
    assert result.latency_ms is not None
    assert result.latency_ms >= 0


def test_package_exports_client_and_result_types() -> None:
    package = import_jev()
    assert package.AsyncJevClient is _client_mod().AsyncJevClient
    assert package.PINNED_MODEL == PINNED_MODEL
    types = import_jev("types")
    assert package.JevCallResult is types.JevCallResult
    assert package.JevError is types.JevError
