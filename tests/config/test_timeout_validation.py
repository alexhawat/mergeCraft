"""Plan W6.3 — timeout input validation fails closed (``#17``).

Contracts:

- An unparseable ``timeout`` input is a ``configuration_error`` at startup,
  not a silent 1h fallback (the ``--notimeout`` escape hatch stays).
- Valid durations keep parsing exactly as today (baseline pins).
"""

from __future__ import annotations

import pytest

from mergecraft.utils.time_parse import (
    TIMEOUT_DISABLED,
    normalize_timeout_input,
    parse_time_string,
    resolve_timeout_ms,
)


@pytest.mark.parametrize(
    ("raw", "expected_ms"),
    [
        ("10m", 600_000),
        ("1h", 3_600_000),
        ("30s", 30_000),
        ("1h30m", 5_400_000),
        ("1h30m45s", 5_445_000),
    ],
    ids=["10m", "1h", "30s", "1h30m", "1h30m45s"],
)
def test_valid_time_strings_parse(raw: str, expected_ms: int) -> None:
    """Baseline — documented formats keep their millisecond values."""
    assert parse_time_string(raw) == expected_ms
    assert resolve_timeout_ms(raw) == expected_ms


@pytest.mark.parametrize(
    "raw",
    ["", "not-a-duration", "10", "1d", "-5m", "0s", "999999999999h", "mm"],
    ids=["empty", "garbage", "unitless", "days", "negative", "zero", "overflow", "unit-only"],
)
def test_invalid_time_strings_resolve_to_none(raw: str) -> None:
    """Baseline — unusable values are detectable as unusable."""
    assert resolve_timeout_ms(raw) is None


def test_notimeout_escape_hatch_survives() -> None:
    """W6.3 — ``--notimeout`` remains the explicit opt-out, distinct from invalid."""
    assert normalize_timeout_input("--notimeout") == TIMEOUT_DISABLED
    assert normalize_timeout_input("none") == TIMEOUT_DISABLED
    assert normalize_timeout_input("garbage") != TIMEOUT_DISABLED


async def test_unparseable_timeout_fails_closed_before_agent_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W6.3 — startup validation: the agent never runs on a bad timeout.

    Fails if the guard is deleted: a silent 1h fallback would let the agent
    run and the outcome would not be ``configuration_error``.
    """
    from tests.support.run_main_harness import run_main_for_test

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        env={"INPUT_TIMEOUT": "not-a-duration"},
    )
    assert rec.result is not None
    assert not rec.result.success
    assert rec.agent_runs == [], f"agent ran despite unparseable timeout: {rec.agent_runs}"
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is not None
    assert outcome.value == "configuration_error", (
        f"expected configuration_error, got {outcome!r} (result: {rec.result})"
    )


async def test_notimeout_still_disables_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """W6.3 — the escape hatch: ``--notimeout`` runs the agent with no deadline."""
    from tests.support.run_main_harness import run_main_for_test

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        env={"INPUT_TIMEOUT": "--notimeout"},
    )
    assert rec.result is not None
    assert rec.result.success, f"run failed: {rec.result}"
    assert rec.agent_runs, "agent did not run under --notimeout"
