"""Agent runtime knobs: the timeout keeps its 3600-second default.

``MERGECRAFT_AGENT_TIMEOUT`` is read by five provider drivers and by the
credential broker. Every read site defaults to ``3600`` and honours a valid
integer; a malformed value fails at the read rather than mid-run. The typed
model owns that parse, and the drivers keep reading the resolved value.

The model does not exist yet, so the model assertions are red; no ``xfail``
marker is used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_DEFAULT_TIMEOUT = 3600

_ALIASES = (
    "MERGECRAFT_AGENT_TIMEOUT",
    "MERGECRAFT_CODEX_HOME_PARENT",
    "MERGECRAFT_MODEL",
    "MERGECRAFT_AGENT",
)


def _agent_runtime_env() -> Any:
    from mergecraft.config.env import AgentRuntimeEnv

    return AgentRuntimeEnv


def _field_for(model: Any, alias: str) -> str:
    for name, field in model.model_fields.items():
        declared = field.validation_alias
        if declared == alias:
            return name
        choices = getattr(declared, "choices", ())
        if alias in choices:
            return name
    msg = f"{model.__name__} does not declare {alias}"
    raise AssertionError(msg)


@pytest.mark.parametrize("alias", _ALIASES)
def test_agent_runtime_env_declares_the_runtime_knobs(alias: str) -> None:
    """Every agent-runtime variable is a declared field with its exact name."""
    model = _agent_runtime_env()
    assert _field_for(model, alias)


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, _DEFAULT_TIMEOUT),
        ({"MERGECRAFT_AGENT_TIMEOUT": ""}, _DEFAULT_TIMEOUT),
        ({"MERGECRAFT_AGENT_TIMEOUT": "3600"}, 3600),
        ({"MERGECRAFT_AGENT_TIMEOUT": "120"}, 120),
        ({"MERGECRAFT_AGENT_TIMEOUT": "1"}, 1),
    ],
)
def test_agent_timeout_defaults_to_3600_and_honours_a_valid_value(
    env: dict[str, str],
    expected: int,
) -> None:
    """Unset, empty and an explicit integer resolve to today's values."""
    model = _agent_runtime_env()
    field_name = _field_for(model, "MERGECRAFT_AGENT_TIMEOUT")

    assert getattr(model.from_env(env), field_name) == expected


@pytest.mark.parametrize("raw", ["soon", "1.5", "10m", "true"])
def test_agent_timeout_rejects_a_malformed_value(raw: str) -> None:
    """A malformed timeout raises ``ValueError`` and never echoes the value."""
    model = _agent_runtime_env()
    field_name = _field_for(model, "MERGECRAFT_AGENT_TIMEOUT")

    with pytest.raises(ValueError, match="MERGECRAFT_AGENT_TIMEOUT") as raised:
        getattr(model.from_env({"MERGECRAFT_AGENT_TIMEOUT": raw}), field_name)

    assert "MERGECRAFT_AGENT_TIMEOUT" in str(raised.value)


def test_agent_timeout_reads_nothing_from_the_process_environment(
    monkeypatch: MonkeyPatch,
) -> None:
    """A mapping-only read never falls back to ``os.environ``."""
    model = _agent_runtime_env()
    field_name = _field_for(model, "MERGECRAFT_AGENT_TIMEOUT")
    monkeypatch.setenv("MERGECRAFT_AGENT_TIMEOUT", "120")

    assert getattr(model.from_env({}), field_name) == _DEFAULT_TIMEOUT


def test_agent_runtime_env_is_constructed_per_read(monkeypatch: MonkeyPatch) -> None:
    """No cached instance: a value written after a read is seen by the next read."""
    model = _agent_runtime_env()
    field_name = _field_for(model, "MERGECRAFT_AGENT_TIMEOUT")

    monkeypatch.setenv("MERGECRAFT_AGENT_TIMEOUT", "120")
    assert getattr(model(), field_name) == 120
    monkeypatch.setenv("MERGECRAFT_AGENT_TIMEOUT", "240")
    assert getattr(model(), field_name) == 240
