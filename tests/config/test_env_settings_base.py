"""Foundation contracts for the ``mergecraft.config.env`` package.

The typed env layer is the base every later setting model registers into. These
tests pin its public building blocks — the boolean vocabulary, the exact-``"1"``
flag, the mapping-only ``from_env`` seam, the model registry and the secret
handling — before any implementation exists.

Every import of ``mergecraft.config.env`` happens **inside the test body**, so
the module collects cleanly while the package does not exist yet and each test
fails on its own. No ``xfail`` marker is used: a not-yet-implemented assertion
is a plain failure, and the repo's xpass ratchet therefore never fires.

The contracts under test are behavioural: a stricter reading of "boolean" than
Pydantic's own (it accepts ``t`` and ``y``), an injectable mapping that must
never fall back to the process environment, and a registry whose dumps must not
contain a credential.
"""

from __future__ import annotations

from typing import Any

import pytest

# ── the vocabulary is a closed set, not Pydantic's bool ─────────────────────

_TRUE_SPELLINGS = [
    "true",
    "TRUE",
    "True",
    "1",
    "yes",
    "YES",
    "on",
    "ON",
    "  true  ",
    "\ttrue\n",
]
_FALSE_SPELLINGS = [
    "false",
    "FALSE",
    "False",
    "0",
    "no",
    "NO",
    "off",
    "OFF",
    "  false  ",
    "\tOFF\n",
]
# Spellings Pydantic's ``bool`` would accept but the env vocabulary must reject.
_REJECTED_SPELLINGS = [
    "t",
    "T",
    "y",
    "Y",
    "ture",
    "maybe",
    "2",
    "-1",
    "truee",
    "1.0",
    " ",
    "",
]


@pytest.mark.parametrize("raw", _TRUE_SPELLINGS)
def test_env_bool_accepts_the_true_spellings(raw: str) -> None:
    """The four true spellings, case-insensitive and stripped, parse True."""
    from mergecraft.config.env import EnvBool
    from pydantic import TypeAdapter

    assert TypeAdapter(EnvBool).validate_python(raw) is True


@pytest.mark.parametrize("raw", _FALSE_SPELLINGS)
def test_env_bool_accepts_the_false_spellings(raw: str) -> None:
    """The four false spellings, case-insensitive and stripped, parse False."""
    from mergecraft.config.env import EnvBool
    from pydantic import TypeAdapter

    assert TypeAdapter(EnvBool).validate_python(raw) is False


@pytest.mark.parametrize("raw", _REJECTED_SPELLINGS)
def test_env_bool_rejects_widened_spellings_as_none(raw: str) -> None:
    """``t`` / ``y`` and every other unknown spelling are ignored (``None``).

    Pydantic's own ``bool`` accepts ``t`` and ``y``; widening a control to
    those spellings is the failure this vocabulary exists to prevent.
    """
    from mergecraft.config.env import EnvBool
    from pydantic import TypeAdapter

    assert TypeAdapter(EnvBool).validate_python(raw) is None


def test_env_bool_none_stays_none() -> None:
    """An absent value parses ``None`` — "no opinion", not ``False``."""
    from mergecraft.config.env import EnvBool
    from pydantic import TypeAdapter

    assert TypeAdapter(EnvBool).validate_python(None) is None


# ── the exact-"1" flag ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", True),
        (" 1", False),
        ("1 ", False),
        ("01", False),
        ("+1", False),
        ("true", False),
        ("TRUE", False),
        ("yes", False),
        ("on", False),
        ("t", False),
        ("0", False),
        ("", False),
        (None, False),
    ],
)
def test_exact_flag_is_enabled_only_by_exactly_one(raw: str | None, expected: bool) -> None:
    """``ExactFlag(raw).enabled`` is exactly ``raw == "1"`` — no trimming, no case."""
    from mergecraft.config.env import ExactFlag

    assert ExactFlag(raw).enabled is expected


# ── the mapping-only `from_env` seam ────────────────────────────────────────


def _env_bool_probe() -> Any:
    """Build a ``BaseSettings`` probe whose ``flag`` field is an ``EnvBool``.

    The probe is a real settings model, so it exercises the type exactly as a
    production model would rather than validating a bare value.
    """
    from mergecraft.config.env import EnvBool
    from pydantic import Field, create_model
    from pydantic_settings import BaseSettings, SettingsConfigDict

    return create_model(
        "_Ps1EnvBoolProbe",
        __base__=BaseSettings,
        __config__=SettingsConfigDict(
            case_sensitive=True,
            extra="ignore",
            env_ignore_empty=True,
        ),
        flag=(EnvBool, Field(default=None, validation_alias="PS1_PROBE_FLAG")),
    )


def test_from_env_reads_nothing_from_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mapping-only read must not fall back to ``os.environ``.

    This is the injectable seam every resolver uses to keep the environment a
    message bus: a field present in ``os.environ`` but absent from the mapping
    stays unset.
    """
    from mergecraft.config.env import from_env

    probe = _env_bool_probe()
    monkeypatch.setenv("PS1_PROBE_FLAG", "true")

    assert from_env(probe, {}).flag is None


def test_from_env_reflects_the_mapping_it_is_given() -> None:
    """The mapping's values are the only input the read honours."""
    from mergecraft.config.env import from_env

    probe = _env_bool_probe()

    assert from_env(probe, {"PS1_PROBE_FLAG": "true"}).flag is True
    assert from_env(probe, {"PS1_PROBE_FLAG": "false"}).flag is False
    assert from_env(probe, {"PS1_PROBE_FLAG": "t"}).flag is None


# ── no cached instance: every read sees the current environment ─────────────


def test_a_later_setenv_is_seen_by_the_next_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second read of the same model reflects a change made after the first."""
    probe = _env_bool_probe()

    monkeypatch.setenv("PS1_PROBE_FLAG", "true")
    assert probe().flag is True

    monkeypatch.setenv("PS1_PROBE_FLAG", "false")
    assert probe().flag is False


def test_registered_models_are_constructed_per_read() -> None:
    """No registered model is a cached singleton.

    ``MERGECRAFT_TEMP_DIR`` and friends are written to ``os.environ`` mid-run
    and read back by other modules, so a process-wide settings cache would
    serve a stale value.
    """
    from mergecraft.config.env import registered_env_models

    models = registered_env_models()
    assert models, "the env registry must carry at least one model after the foundation lands"

    for model in models:
        assert model() is not model()


# ── the registry and the startup validation ─────────────────────────────────


def test_registered_models_are_settings_models() -> None:
    """Every registered model is a ``BaseSettings`` the startup gate can validate."""
    from mergecraft.config.env import registered_env_models
    from pydantic_settings import BaseSettings

    models = registered_env_models()
    assert models
    assert all(issubclass(model, BaseSettings) for model in models)


def test_validate_env_settings_is_callable() -> None:
    """The startup registry has one entry point the Action calls once."""
    from mergecraft.config.env import validate_env_settings

    assert callable(validate_env_settings)


# ── secrets never reach a repr or a dump ────────────────────────────────────

_CANARY_VALUE = "ps1canarymarkervalue"


def _first_alias(field: Any) -> str | None:
    """Return the first string env alias a field declares, or ``None``."""
    alias = field.validation_alias
    if isinstance(alias, str):
        return alias
    choices = getattr(alias, "choices", ())
    for choice in choices:
        if isinstance(choice, str):
            return choice
    return None


def _is_secret_annotation(annotation: Any) -> bool:
    """Return whether a field annotation is (or wraps) ``SecretStr``."""
    return "SecretStr" in str(annotation)


def test_no_registered_model_dump_leaks_a_secret() -> None:
    """``repr`` / ``model_dump`` / ``model_dump_json`` mask every secret field."""
    from mergecraft.config.env import from_env, registered_env_models
    from pydantic import SecretStr

    secret_models = 0
    for model in registered_env_models():
        mapping: dict[str, str] = {}
        for _name, field in model.model_fields.items():
            if _is_secret_annotation(field.annotation):
                alias = _first_alias(field)
                if alias:
                    mapping[alias] = _CANARY_VALUE
        if not mapping:
            continue
        secret_models += 1
        instance = from_env(model, mapping)
        blob = f"{instance!r}\n{instance.model_dump()!s}\n{instance.model_dump_json()}"
        assert _CANARY_VALUE not in blob, (
            f"{model.__name__} leaked a secret value through repr/dump/model_dump_json"
        )
        for name, field in model.model_fields.items():
            if _is_secret_annotation(field.annotation):
                assert isinstance(getattr(instance, name), SecretStr) or isinstance(
                    getattr(instance, name, None), SecretStr
                ), f"{model.__name__}.{name} is a secret field but is not typed SecretStr"

    assert secret_models >= 1, (
        "at least one registered model must carry a SecretStr field (the .env token)"
    )


# ── the configuration error names the variable and never the value ──────────


def test_env_settings_error_is_a_value_error() -> None:
    """Callers that already catch ``ValueError`` keep failing closed."""
    from mergecraft.config.env import EnvSettingsError

    assert issubclass(EnvSettingsError, ValueError)


def test_env_settings_error_names_the_variable_never_the_value() -> None:
    """The message names the offending variable; the value is never echoed."""
    from mergecraft.config.env import EnvSettingsError

    error = EnvSettingsError("MERGECRAFT_TRACING", _CANARY_VALUE)
    message = str(error)

    assert "MERGECRAFT_TRACING" in message
    assert _CANARY_VALUE not in message
