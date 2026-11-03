"""A review profile exports only the environment variables the run-bounds reader consumes.

``profile_env_overrides`` used to export a latency budget and a profile name
that nothing read. The three budget variables are consumed by
``utils/run_bounds.resolve_run_bounds`` through ``RunBoundsEnv``;
``latency_budget_ms`` stays a recorded field on the profile.

The accepted set is derived from the model that owns the parse, not from the
text of ``utils/run_bounds.py``: the parser moved into ``RunBoundsEnv``, so a
source-text scrape of the resolver no longer sees the variable names.
"""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.cli.profiles import profile_env_overrides, resolve_profile
from mergecraft.utils.run_bounds import resolve_run_bounds


def _declared_aliases(model: Any) -> frozenset[str]:
    """Every exact environment name *model* declares."""
    names: set[str] = set()
    for field in model.model_fields.values():
        alias = field.validation_alias
        if isinstance(alias, str):
            names.add(alias)
            continue
        names.update(choice for choice in getattr(alias, "choices", ()) if isinstance(choice, str))
    return frozenset(names)


def _read_env() -> frozenset[str]:
    """The run-bounds reader's accepted set, as the model declares it."""
    from mergecraft.config.env import RunBoundsEnv

    return _declared_aliases(RunBoundsEnv)


_READ_ENV = _read_env()
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
    """Every exported key is one the run-bounds model resolves."""
    profile = resolve_profile(profile_name)
    assert profile is not None
    emitted = set(profile_env_overrides(profile))
    # Guard the oracle: the model must still declare the budget bundle, otherwise
    # the subset check is weaker than it looks.
    assert _READ_ENV >= _BUDGET_VARS, sorted(_BUDGET_VARS - _READ_ENV)
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
