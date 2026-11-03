"""Agent runtime knobs: the timeout keeps its 3600-second default.

``MERGECRAFT_AGENT_TIMEOUT`` is read by five provider drivers and by the
credential broker. Every read site defaulted to ``3600`` and honoured a valid
integer; a malformed value failed at the read rather than mid-run. The typed
model owns that parse, and the drivers keep reading the resolved value.

The provider drivers used ``int(os.environ.get("MERGECRAFT_AGENT_TIMEOUT",
"3600"))``, so an **empty** value raised ``ValueError`` from ``int("")`` while an
absent value took the default. ``env_ignore_empty=True`` would silently turn
``""`` into ``3600`` and move that empty-value rule, so the empty case is pinned
here as a raise. The last test audits every other numeric run-budget/timeout
knob for the same corruption.

The model does not exist yet, so the model assertions are red; no ``xfail``
marker is used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.utils.run_bounds import resolve_run_bounds

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
        ({"MERGECRAFT_AGENT_TIMEOUT": "3600"}, 3600),
        ({"MERGECRAFT_AGENT_TIMEOUT": "120"}, 120),
        ({"MERGECRAFT_AGENT_TIMEOUT": "1"}, 1),
    ],
)
def test_agent_timeout_defaults_to_3600_and_honours_a_valid_value(
    env: dict[str, str],
    expected: int,
) -> None:
    """Unset and an explicit integer resolve to today's values; empty does not."""
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


@pytest.mark.parametrize("raw", ["", "   "])
def test_agent_timeout_rejects_an_empty_value_like_today(raw: str) -> None:
    """An empty or blank timeout raised from ``int(...)``; it must still raise.

    ``env_ignore_empty=True`` would make ``""`` read as absent and return
    ``3600``. That is a different setting, not a parity-preserving parse, so the
    empty case stays a failure that names the variable.
    """
    model = _agent_runtime_env()
    field_name = _field_for(model, "MERGECRAFT_AGENT_TIMEOUT")

    with pytest.raises(ValueError, match="MERGECRAFT_AGENT_TIMEOUT") as raised:
        getattr(model.from_env({"MERGECRAFT_AGENT_TIMEOUT": raw}), field_name)

    assert "MERGECRAFT_AGENT_TIMEOUT" in str(raised.value)


#: Every other numeric run-budget/timeout knob and today's empty-value rule.
#:
#: ``_env_int`` / ``_env_float`` returned ``None`` for an empty value, so each
#: run-budget knob fell through exactly as if it were unset. The MCP port's own
#: ``if not raw`` guard does the same. Only the agent timeout parsed with a bare
#: ``int()``, which made the empty string an error.
_EMPTY_VALUE_PARITY: tuple[tuple[str, str, str], ...] = (
    ("AgentRuntimeEnv", "MERGECRAFT_AGENT_TIMEOUT", "raise"),
    ("RunBoundsEnv", "MERGECRAFT_TOKEN_BUDGET", "absent"),
    ("RunBoundsEnv", "MERGECRAFT_COST_BUDGET_USD", "absent"),
    ("RunBoundsEnv", "MERGECRAFT_TOOL_CALL_BUDGET", "absent"),
    ("RunBoundsEnv", "MERGECRAFT_MAX_DIFF_LINES", "absent"),
    ("RunBoundsEnv", "MERGECRAFT_CONTEXT_RETRIEVAL_TIMEOUT_S", "absent"),
    ("RunBoundsEnv", "MERGECRAFT_RUN_TIMEOUT_S", "absent"),
    ("RunBoundsEnv", "MERGECRAFT_EXTERNAL_OPERATION_TIMEOUT_S", "absent"),
    ("RunBoundsEnv", "MERGECRAFT_CACHE_MAX_BYTES", "absent"),
    ("McpEnv", "MERGECRAFT_MCP_PORT", "absent"),
)


@pytest.mark.parametrize(
    ("model_name", "knob", "empty_rule"),
    _EMPTY_VALUE_PARITY,
    ids=[f"{knob}-{rule}" for _, knob, rule in _EMPTY_VALUE_PARITY],
)
def test_numeric_knobs_do_not_turn_an_empty_value_into_a_default(
    model_name: str,
    knob: str,
    empty_rule: str,
) -> None:
    """``env_ignore_empty`` must reproduce today's empty rule for every numeric knob."""
    import mergecraft.config.env as env_package

    model = getattr(env_package, model_name)
    field_name = _field_for(model, knob)

    if empty_rule == "raise":
        with pytest.raises(ValueError, match=knob) as raised:
            getattr(model.from_env({knob: ""}), field_name)
        assert knob in str(raised.value)
        return

    assert getattr(model.from_env({knob: ""}), field_name) is None, (
        f"{knob}= is absent today, not a resolved value"
    )
    if model_name == "RunBoundsEnv":
        assert resolve_run_bounds(env={knob: ""}) == resolve_run_bounds(env={}), (
            f"{knob}= must resolve exactly like unset"
        )


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
