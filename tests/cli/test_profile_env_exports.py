"""A review profile exports only the environment variables the run-bounds reader consumes.

``profile_env_overrides`` used to export a latency budget and a profile name
that nothing read. The three budget variables are consumed by
``utils/run_bounds.resolve_run_bounds``; ``latency_budget_ms`` stays a recorded
field on the profile.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mergecraft.cli.profiles import profile_env_overrides, resolve_profile
from mergecraft.utils.run_bounds import resolve_run_bounds

_RUN_BOUNDS_SOURCE = (
    Path(__file__).resolve().parents[2] / "src" / "mergecraft" / "utils" / "run_bounds.py"
)
_READ_ENV = frozenset(
    re.findall(r"MERGECRAFT_[A-Z0-9_]+", _RUN_BOUNDS_SOURCE.read_text(encoding="utf-8"))
)
_LATENCY_VAR = "MERGECRAFT_LATENCY_BUDGET_MS"
_PROFILE_VAR = "MERGECRAFT_PROFILE"
_BUDGET_VARS = frozenset(
    {
        "MERGECRAFT_TOKEN_BUDGET",
        "MERGECRAFT_COST_BUDGET_USD",
        "MERGECRAFT_TOOL_CALL_BUDGET",
    }
)


@pytest.mark.parametrize("profile_name", ["fast", "deep", "security"])
def test_profile_env_overrides_emits_no_unread_variable(profile_name: str) -> None:
    """Every exported key is one the run-bounds reader resolves."""
    profile = resolve_profile(profile_name)
    assert profile is not None
    emitted = set(profile_env_overrides(profile))
    assert emitted <= _READ_ENV, sorted(emitted - _READ_ENV)
    assert _LATENCY_VAR not in emitted
    assert _PROFILE_VAR not in emitted
    # Surviving surface: the budget bundle and the recorded latency field stay.
    assert emitted >= _BUDGET_VARS
    assert profile.token_budget > 0
    assert profile.latency_budget_ms > 0


@pytest.mark.parametrize(
    ("env_name", "value", "attribute"),
    [
        ("MERGECRAFT_TOKEN_BUDGET", "12345", "token_budget"),
        ("MERGECRAFT_COST_BUDGET_USD", "1.25", "cost_budget_usd"),
        ("MERGECRAFT_TOOL_CALL_BUDGET", "77", "tool_call_budget"),
    ],
)
def test_exported_budget_variable_actually_changes_resolved_bounds(
    env_name: str,
    value: str,
    attribute: str,
) -> None:
    """An exported variable is one ``resolve_run_bounds`` reads and applies."""
    profile = resolve_profile("deep")
    assert profile is not None
    assert set(profile_env_overrides(profile)) == _BUDGET_VARS
    baseline = resolve_run_bounds()
    overridden = resolve_run_bounds(env={env_name: value})
    assert getattr(overridden, attribute) != getattr(baseline, attribute)
    # Surviving surface: the resolved bound stays positive.
    assert getattr(overridden, attribute) > 0
