"""Published Go rates, UTC boundaries, and honest unavailable-price behavior."""

from datetime import datetime

import pytest

from mergecraft.agents.opencode_pricing import estimate_go_step_cost


@pytest.mark.parametrize(
    ("at", "expected"),
    [
        ("2026-11-02T00:59:59+00:00", 0.753),
        ("2026-11-02T01:00:00+00:00", 1.506),
        ("2026-11-02T03:59:59+00:00", 1.506),
        ("2026-11-02T04:00:00+00:00", 0.753),
        ("2026-11-02T05:59:59+00:00", 0.753),
        ("2026-11-02T06:00:00+00:00", 1.506),
        ("2026-11-02T09:59:59+00:00", 1.506),
        ("2026-11-02T10:00:00+00:00", 0.753),
        ("2026-11-01T02:00:00+00:00", 0.753),
        ("2026-10-31T07:00:00+00:00", 0.753),
        ("2026-11-02T02:00:00+02:00", 0.753),
    ],
)
def test_flash_prices_each_utc_window(at: str, expected: float) -> None:
    assert estimate_go_step_cost(
        model="opencode-go/deepseek-v4.1-flash",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_tokens=1_000_000,
        cache_write_tokens=0,
        timestamp_ms=datetime.fromisoformat(at).timestamp() * 1000,
    ) == pytest.approx(expected)


@pytest.mark.parametrize(("hour", "expected"), [(0, 2.662), (1, 5.324)])
def test_pro_has_its_own_published_rates(hour: int, expected: float) -> None:
    at = datetime.fromisoformat(f"2026-11-02T0{hour}:00:00+00:00")
    assert estimate_go_step_cost(
        model="opencode-go/deepseek-v4-pro",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_tokens=1_000_000,
        cache_write_tokens=0,
        timestamp_ms=at.timestamp() * 1000,
    ) == pytest.approx(expected)


@pytest.mark.parametrize("timestamp", [None, "yesterday", True, float("nan"), float("inf"), 1e30])
def test_missing_or_invalid_timestamp_does_not_guess_the_price(timestamp: object) -> None:
    assert (
        estimate_go_step_cost(
            model="opencode-go/deepseek-v4.1-flash",
            input_tokens=1_000_000,
            output_tokens=1,
            cache_read_tokens=0,
            cache_write_tokens=0,
            timestamp_ms=timestamp,
        )
        is None
    )


@pytest.mark.parametrize(
    "model", [None, "opencode-go/unknown", "deepseek/deepseek-v4.1-flash", "deepseek-v4.1-flash"]
)
def test_rates_never_leak_to_other_providers_or_models(model: str | None) -> None:
    assert (
        estimate_go_step_cost(
            model=model,
            input_tokens=1_000_000,
            output_tokens=1,
            cache_read_tokens=0,
            cache_write_tokens=0,
            timestamp_ms=1793491200000,
        )
        is None
    )


@pytest.mark.parametrize(("input_tokens", "cache_write"), [(-1, 0), (1000, 50)])
def test_unpriced_cache_write_or_invalid_counters_stay_unknown(
    input_tokens: int, cache_write: int
) -> None:
    assert (
        estimate_go_step_cost(
            model="opencode-go/deepseek-v4.1-flash",
            input_tokens=input_tokens,
            output_tokens=1,
            cache_read_tokens=0,
            cache_write_tokens=cache_write,
            timestamp_ms=1793491200000,
        )
        is None
    )
