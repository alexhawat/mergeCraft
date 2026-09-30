"""Shared building blocks for the typed environment settings layer.

This package is a leaf: every module here imports only ``pydantic``,
``pydantic_settings``, ``python-dotenv`` and the package itself, so it can
never join the lazy-import cycle that ``mergecraft.config.settings`` works
around. The environment is read through models here and nowhere else.

Exports:
    ENV_SETTINGS_CONFIG: shared ``SettingsConfigDict`` for process-env models.
    EnvBool: the closed boolean vocabulary (never Pydantic's ``bool``).
    ExactFlag: a raw value whose only enabled spelling is exactly ``"1"``.
    EnvSettingsError: a malformed value that must fail configuration.
    EnvSettings: base model; construction surfaces ``EnvSettingsError``.
    fail_closed_env_bool: the control-variable boolean (unknown value raises).
    from_env: validate a mapping without touching ``os.environ``.
    register_env_model: add a model to the startup validation registry.
    registered_env_models: the registry, as classes (never cached instances).
    validate_env_settings: construct every registered model once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, NoReturn, Self, TypeVar, cast

from pydantic import BeforeValidator, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "ENV_SETTINGS_CONFIG",
    "EnvBool",
    "EnvSettings",
    "EnvSettingsError",
    "ExactFlag",
    "fail_closed_env_bool",
    "from_env",
    "register_env_model",
    "registered_env_models",
    "validate_env_settings",
]

# Shared defaults for every process-env model. Variable names are exact
# (``case_sensitive``), unknown variables are ignored, and an empty value means
# "absent" — reproducing today's empty-string behaviour. A model overrides a
# key only where the parity table proves today's behaviour differs.
ENV_SETTINGS_CONFIG = SettingsConfigDict(
    case_sensitive=True,
    extra="ignore",
    env_ignore_empty=True,
)

_TRUE_SPELLINGS = frozenset({"true", "1", "yes", "on"})
_FALSE_SPELLINGS = frozenset({"false", "0", "no", "off"})

_ModelT = TypeVar("_ModelT", bound=BaseSettings)


def _parse_env_bool(value: Any) -> bool | None:
    """Map the closed boolean vocabulary to ``True`` / ``False`` / ``None``.

    Exactly ``true/1/yes/on`` and ``false/0/no/off`` are recognized, case
    insensitively and stripped. Everything else — including Pydantic's own
    ``t`` and ``y``, and an empty string — is "no opinion" (``None``), so a typo
    can never widen a control that today reads one spelling.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_SPELLINGS:
            return True
        if normalized in _FALSE_SPELLINGS:
            return False
    return None


#: The closed boolean vocabulary. Usable as a field annotation and directly
#: through ``TypeAdapter(EnvBool)``.
EnvBool = Annotated[bool | None, BeforeValidator(_parse_env_bool)]


class ExactFlag:
    """A raw environment value whose only enabled spelling is exactly ``"1"``.

    Control-weakening switches are enabled by exactly ``"1"`` today. Typing one
    as ``bool`` would also accept ``true`` / ``yes`` / ``on`` and widen the
    control, so the switch keeps its raw value and compares it verbatim — no
    trimming, no case folding.
    """

    __slots__ = ("raw",)

    def __init__(self, raw: str | None = None) -> None:
        self.raw = raw

    @property
    def enabled(self) -> bool:
        """True only for the literal string ``"1"``."""
        return self.raw == "1"

    def __repr__(self) -> str:
        return f"ExactFlag({self.raw!r})"


class EnvSettingsError(ValueError):
    """A malformed environment value that must fail configuration.

    The message names the offending variable and never repeats the value, so
    the error can cross a logging boundary without leaking a credential. The
    value is accepted for call-site symmetry and is deliberately discarded.
    """

    def __init__(self, variable: str, value: object = None) -> None:
        del value  # never retained: the value may be a secret
        self.variable = variable
        super().__init__(f"invalid value for environment variable {variable}")


def fail_closed_env_bool(variable: str, value: Any) -> bool | None:
    """Parse a control-carrying boolean, raising on a non-empty unknown value.

    The vocabulary is exactly :data:`EnvBool`'s (``true/1/yes/on`` /
    ``false/0/no/off``, case-insensitive and stripped). The difference is the
    unknown case: a non-empty value outside that set raises
    :class:`EnvSettingsError` naming *variable* instead of being ignored, so a
    typo meant to *disable* a control cannot let a lower precedence layer's more
    permissive value stand (fail closed). An absent value, ``None``, and an
    empty or whitespace-only value are still "no opinion" (``None``).

    The message names the variable and never the value, so the error can cross a
    logging boundary without leaking a credential.
    """
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    parsed = _parse_env_bool(value)
    if parsed is None:
        raise EnvSettingsError(variable)
    return parsed


def _raise_env_settings_error(error: ValidationError) -> NoReturn:
    """Re-raise a wrapped :class:`EnvSettingsError`, else the ``ValidationError``.

    Pydantic converts a ``ValueError`` raised in a validator — including
    :class:`EnvSettingsError` — into a ``ValidationError``. The original is
    recoverable from the error entry's context, so a fail-closed validator
    surfaces as the configuration error its caller expects.
    """
    for entry in error.errors():
        cause = (entry.get("ctx") or {}).get("error")
        if isinstance(cause, EnvSettingsError):
            raise cause from error
    raise error


class EnvSettings(BaseSettings):
    """Base for every typed environment model in this package.

    Construction surfaces a fail-closed :class:`EnvSettingsError` out of the
    ``ValidationError`` Pydantic wraps it in, so a caller that reads a setting
    lazily catches the configuration error directly. A genuinely malformed
    numeric value still raises ``ValidationError`` — itself a ``ValueError``.
    """

    model_config = ENV_SETTINGS_CONFIG

    def __init__(self, *args: Any, **values: Any) -> None:
        try:
            super().__init__(*args, **values)
        except ValidationError as error:
            _raise_env_settings_error(error)

    @classmethod
    def from_env(cls, env: Mapping[str, Any]) -> Self:
        """Validate *env* through this model without reading ``os.environ``."""
        return from_env(cls, env)


def _init_only_settings_sources(
    settings_cls: type[BaseSettings],
    init_settings: Any,
    env_settings: Any,
    dotenv_settings: Any,
    file_secret_settings: Any,
) -> tuple[Any, ...]:
    """Return just the init source, keeping the process environment out.

    Pydantic-settings looks this hook up on the class and calls it with the
    built-in sources; returning only ``init_settings`` makes the mapping the
    sole input of the read.
    """
    return (init_settings,)


def from_env(model_cls: type[_ModelT], env: Mapping[str, Any]) -> _ModelT:
    """Validate *env* through *model_cls* reading nothing else.

    The mapping is the only input. An ``init_settings``-only source list keeps
    ``os.environ`` out of the read — so a resolver can hand the mapping down
    unchanged and a ``monkeypatch.setenv`` after an earlier read is still seen,
    because no instance is cached. Empty values are dropped exactly as the
    model's ``env_ignore_empty`` setting would drop them.
    """
    ignore_empty = bool(model_cls.model_config.get("env_ignore_empty", True))
    provided: dict[str, Any] = {
        key: value
        for key, value in env.items()
        if not (ignore_empty and isinstance(value, str) and value == "")
    }
    # ``type()`` cannot be typed statically; the cast names the dynamic subclass.
    mapping_only = cast(
        "type[_ModelT]",
        type(
            f"{model_cls.__name__}FromMapping",
            (model_cls,),
            {"settings_customise_sources": _init_only_settings_sources},
        ),
    )
    try:
        return mapping_only(**provided)
    except ValidationError as error:
        _raise_env_settings_error(error)


_ENV_MODELS: list[type[BaseSettings]] = []


def register_env_model(model: type[_ModelT]) -> type[_ModelT]:
    """Register *model* for the one startup validation pass (idempotent)."""
    if model not in _ENV_MODELS:
        _ENV_MODELS.append(model)
    return model


def registered_env_models() -> tuple[type[BaseSettings], ...]:
    """Return the registered models. Each read constructs a fresh instance."""
    return tuple(_ENV_MODELS)


def validate_env_settings() -> None:
    """Construct every registered model once so a malformed value fails early.

    Nothing is cached: construction reads the current environment, so a value
    written mid-run is seen by the next read. A malformed value raises
    :class:`EnvSettingsError`, which names the variable and never the value.
    """
    for model in registered_env_models():
        try:
            model()
        except ValidationError as error:
            _raise_env_settings_error(error)
