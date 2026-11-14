"""Run-budget parity: the eight knobs keep today's resolution, through a model.

The run-budget resolver is the one place where a numeric environment knob has
two different fall-through rules: an integer ``0`` means "unset" (``or cfg.x``)
while a float ``0`` is a real budget (``is None``). That asymmetry is frozen
here, as a literal table produced by running the pre-migration resolver over the
input grid, so the table — not the deleted ``_env_int`` / ``_env_float``
helpers — is the oracle.

``RunBoundsEnv`` owns the parse and nothing else: the resolver keeps its merge
arithmetic, and a malformed value still raises a ``ValueError`` (a
``ValidationError``) that names the variable and never echoes the value.

The model does not exist yet, so the model-shape assertions are red; no
``xfail`` marker is used.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.utils.run_bounds import resolve_run_bounds

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo

#: knob -> the ``RunBounds`` field it resolves into.
_FIELD: dict[str, str] = {
    "MERGECRAFT_TOKEN_BUDGET": "token_budget",
    "MERGECRAFT_COST_BUDGET_USD": "cost_budget_usd",
    "MERGECRAFT_TOOL_CALL_BUDGET": "tool_call_budget",
    "MERGECRAFT_MAX_DIFF_LINES": "max_diff_lines",
    "MERGECRAFT_CONTEXT_RETRIEVAL_TIMEOUT_S": "context_retrieval_timeout_s",
    "MERGECRAFT_RUN_TIMEOUT_S": "run_timeout_s",
    "MERGECRAFT_EXTERNAL_OPERATION_TIMEOUT_S": "external_operation_timeout_s",
    "MERGECRAFT_CACHE_MAX_BYTES": "cache_max_bytes",
}

#: The one well-formed value per knob, and its resolved field value.
_VALID: dict[str, tuple[str, int | float]] = {
    "MERGECRAFT_TOKEN_BUDGET": ("123", 123),
    "MERGECRAFT_COST_BUDGET_USD": ("1.25", 1.25),
    "MERGECRAFT_TOOL_CALL_BUDGET": ("7", 7),
    "MERGECRAFT_MAX_DIFF_LINES": ("99", 99),
    "MERGECRAFT_CONTEXT_RETRIEVAL_TIMEOUT_S": ("2.5", 2.5),
    "MERGECRAFT_RUN_TIMEOUT_S": ("42.5", 42.5),
    "MERGECRAFT_EXTERNAL_OPERATION_TIMEOUT_S": ("3.5", 3.5),
    "MERGECRAFT_CACHE_MAX_BYTES": ("1024", 1024),
}

#: Frozen table: (knob, case) -> resolved field value. Produced by running the
#: pre-migration ``resolve_run_bounds(env=...)`` over ``default_settings()``.
#:
#: The two quirks the plan pins on purpose (PS-D17): an integer ``0`` falls
#: through to the configured value, a float ``0`` is honoured.
_FROZEN: dict[tuple[str, str], int | float] = {
    ("MERGECRAFT_TOKEN_BUDGET", "unset"): 2_000_000,
    ("MERGECRAFT_TOKEN_BUDGET", "empty"): 2_000_000,
    ("MERGECRAFT_TOKEN_BUDGET", "blank"): 2_000_000,
    ("MERGECRAFT_TOKEN_BUDGET", "zero"): 2_000_000,  # `or cfg.x` — falls through
    ("MERGECRAFT_COST_BUDGET_USD", "unset"): 3.0,
    ("MERGECRAFT_COST_BUDGET_USD", "empty"): 3.0,
    ("MERGECRAFT_COST_BUDGET_USD", "blank"): 3.0,
    ("MERGECRAFT_COST_BUDGET_USD", "zero"): 0.0,  # `is None` — honoured
    ("MERGECRAFT_TOOL_CALL_BUDGET", "unset"): 500,
    ("MERGECRAFT_TOOL_CALL_BUDGET", "empty"): 500,
    ("MERGECRAFT_TOOL_CALL_BUDGET", "blank"): 500,
    ("MERGECRAFT_TOOL_CALL_BUDGET", "zero"): 500,  # falls through
    ("MERGECRAFT_MAX_DIFF_LINES", "unset"): 50_000,
    ("MERGECRAFT_MAX_DIFF_LINES", "empty"): 50_000,
    ("MERGECRAFT_MAX_DIFF_LINES", "blank"): 50_000,
    ("MERGECRAFT_MAX_DIFF_LINES", "zero"): 50_000,  # falls through
    ("MERGECRAFT_CONTEXT_RETRIEVAL_TIMEOUT_S", "unset"): 30.0,
    ("MERGECRAFT_CONTEXT_RETRIEVAL_TIMEOUT_S", "empty"): 30.0,
    ("MERGECRAFT_CONTEXT_RETRIEVAL_TIMEOUT_S", "blank"): 30.0,
    ("MERGECRAFT_CONTEXT_RETRIEVAL_TIMEOUT_S", "zero"): 0.0,  # honoured
    ("MERGECRAFT_RUN_TIMEOUT_S", "unset"): 3600.0,
    ("MERGECRAFT_RUN_TIMEOUT_S", "empty"): 3600.0,
    ("MERGECRAFT_RUN_TIMEOUT_S", "blank"): 3600.0,
    ("MERGECRAFT_RUN_TIMEOUT_S", "zero"): 0.0,  # honoured
    ("MERGECRAFT_EXTERNAL_OPERATION_TIMEOUT_S", "unset"): 600.0,
    ("MERGECRAFT_EXTERNAL_OPERATION_TIMEOUT_S", "empty"): 600.0,
    ("MERGECRAFT_EXTERNAL_OPERATION_TIMEOUT_S", "blank"): 600.0,
    ("MERGECRAFT_EXTERNAL_OPERATION_TIMEOUT_S", "zero"): 0.0,  # honoured
    ("MERGECRAFT_CACHE_MAX_BYTES", "unset"): 536_870_912,
    ("MERGECRAFT_CACHE_MAX_BYTES", "empty"): 536_870_912,
    ("MERGECRAFT_CACHE_MAX_BYTES", "blank"): 536_870_912,
    ("MERGECRAFT_CACHE_MAX_BYTES", "zero"): 536_870_912,  # falls through
}

_CASES: list[tuple[str, str]] = [
    (knob, case) for knob in _FIELD for case in ("unset", "empty", "blank", "zero", "valid")
]

#: Malformed values raise; the table never carries a resolved number for them.
_MALFORMED = "soon"


def _env_for(knob: str, case: str) -> dict[str, str]:
    if case == "unset":
        return {}
    if case == "empty":
        return {knob: ""}
    if case == "blank":
        return {knob: "   "}
    if case == "zero":
        return {knob: "0"}
    raw, _ = _VALID[knob]
    return {knob: raw}


def _expected(knob: str, case: str) -> int | float:
    if case == "valid":
        return _VALID[knob][1]
    return _FROZEN[(knob, case)]


@pytest.mark.parametrize(("knob", "case"), _CASES, ids=[f"{k}-{c}" for k, c in _CASES])
def test_resolve_run_bounds_keeps_the_frozen_table(knob: str, case: str) -> None:
    """The resolver returns the frozen value for every knob and every case."""
    bounds = resolve_run_bounds(env=_env_for(knob, case))
    assert getattr(bounds, _FIELD[knob]) == _expected(knob, case)


@pytest.mark.parametrize("knob", sorted(_FIELD), ids=sorted(_FIELD))
def test_malformed_run_budget_still_raises_value_error(knob: str) -> None:
    """A malformed numeric knob stays a ``ValueError`` and names the variable.

    ``ValidationError`` is a ``ValueError`` subclass, so today's "raises
    ``ValueError``" contract holds; the message names the variable and never
    repeats the value.
    """
    with pytest.raises(ValueError, match=re.escape(knob)) as raised:
        resolve_run_bounds(env={knob: _MALFORMED})

    assert knob in str(raised.value), f"the error must name {knob}: {raised.value}"


def test_integer_zero_and_float_zero_keep_their_own_rules() -> None:
    """`MERGECRAFT_TOKEN_BUDGET=0` falls through; `MERGECRAFT_COST_BUDGET_USD=0` does not."""
    bounds = resolve_run_bounds(
        env={"MERGECRAFT_TOKEN_BUDGET": "0", "MERGECRAFT_COST_BUDGET_USD": "0"}
    )
    assert bounds.token_budget == 2_000_000
    assert bounds.cost_budget_usd == 0.0


def test_a_configured_value_still_wins_when_the_knob_is_absent() -> None:
    """The model owns the parse; the resolver keeps the config fall-through."""
    from mergecraft.config.settings import default_settings

    settings = default_settings()
    run_bounds = settings.run_bounds.model_copy(
        update={"token_budget": 111, "cost_budget_usd": 22.5, "tool_call_budget": 33}
    )
    settings = settings.model_copy(update={"run_bounds": run_bounds})

    resolved = resolve_run_bounds(settings=settings, env={})
    assert resolved.token_budget == 111
    assert resolved.cost_budget_usd == 22.5
    assert resolved.tool_call_budget == 33


# ── the model owns the parse ────────────────────────────────────────────────


def _run_bounds_model() -> Any:
    from mergecraft.config.env import RunBoundsEnv

    return RunBoundsEnv


def _field_for(model: Any, alias: str) -> str:
    """Return the model field name declaring *alias*."""
    for name, field in model.model_fields.items():
        declared = field.validation_alias
        if declared == alias:
            return name
        choices = getattr(declared, "choices", ())
        if alias in choices:
            return name
    msg = f"{model.__name__} does not declare {alias}"
    raise AssertionError(msg)


@pytest.mark.parametrize("knob", sorted(_FIELD), ids=sorted(_FIELD))
def test_run_bounds_env_model_parses_every_knob(knob: str) -> None:
    """``RunBoundsEnv`` exposes each knob as an ``int | float | None`` field."""
    model = _run_bounds_model()
    field_name = _field_for(model, knob)
    annotation = str(model.model_fields[field_name].annotation)

    assert "int" in annotation or "float" in annotation, (
        f"{model.__name__}.{field_name} must be numeric, got {annotation}"
    )

    raw, expected = _VALID[knob]
    assert getattr(model.from_env({knob: raw}), field_name) == expected
    assert getattr(model.from_env({knob: "0"}), field_name) == 0
    for unset in ({}, {knob: ""}, {knob: "   "}):
        assert getattr(model.from_env(unset), field_name) is None, (
            f"{knob}={unset.get(knob)!r} must read as absent"
        )


def test_run_bounds_env_model_reads_nothing_from_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mapping-only read never falls back to ``os.environ``."""
    model = _run_bounds_model()
    field_name = _field_for(model, "MERGECRAFT_TOKEN_BUDGET")
    monkeypatch.setenv("MERGECRAFT_TOKEN_BUDGET", "123")

    assert getattr(model.from_env({}), field_name) is None


@pytest.mark.parametrize(
    ("knob", "raw"),
    [
        ("MERGECRAFT_TOKEN_BUDGET", "soon"),
        ("MERGECRAFT_COST_BUDGET_USD", "soon"),
        ("MERGECRAFT_TOKEN_BUDGET", "1.5"),
    ],
)
def test_run_bounds_env_model_raises_on_a_malformed_value(knob: str, raw: str) -> None:
    """A malformed value raises ``ValidationError`` — a ``ValueError`` — naming the knob."""
    model = _run_bounds_model()
    field_name = _field_for(model, knob)

    with pytest.raises(ValueError, match=re.escape(knob)) as raised:
        getattr(model.from_env({knob: raw}), field_name)

    assert knob in str(raised.value)


def test_run_bounds_env_is_registered() -> None:
    """The startup pass validates the run-budget model too."""
    from mergecraft.config.env import registered_env_models

    assert _run_bounds_model() in registered_env_models()


def _first_alias(field: FieldInfo) -> str | None:
    alias = field.validation_alias
    if isinstance(alias, str):
        return alias
    choices = getattr(alias, "choices", ())
    return next((choice for choice in choices if isinstance(choice, str)), None)


def test_run_bounds_env_declares_no_other_environment_name() -> None:
    """The model covers the eight knobs and no other operator knob."""
    model = _run_bounds_model()
    declared = {_first_alias(field) for field in model.model_fields.values()}
    assert declared == set(_FIELD), f"unexpected aliases: {sorted(declared ^ set(_FIELD))}"
