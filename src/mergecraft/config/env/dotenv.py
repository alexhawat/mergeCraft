"""The one ``.env`` parser: a pydantic-settings source over ``python-dotenv``.

``DotEnvFileSource`` wraps the exact ladder ``load_dotenv`` runs — Python
``dotenv``'s :class:`~dotenv.main.DotEnv` with UTF-8, interpolation on and no
override — and yields every key it resolves to a non-``None`` value. It
deliberately does not use pydantic-settings' built-in dotenv source, which
drops a ``KEY=`` line (a present empty value) that ``load_dotenv`` keeps.

``LocalDotEnv`` is the typed view of a file: the declared fields are the
``.env``-resident settings (including a credential as a ``SecretStr``), and
``extra="allow"`` keeps every other key so the whole file can be read back
verbatim. The process environment is never a source of this model; callers
copy the file's keys into ``os.environ`` or pass ``os.environ`` to
:func:`mergecraft.config.env.from_env` when they need a typed process-env read.

Exports:
    DotEnvFileSource: a settings source that reads one ``.env`` file.
    LocalDotEnv: the ``.env`` model, plus ``from_file`` and ``raw_values``.
    local_dotenv_values: the raw string map of one ``.env`` file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, cast

from dotenv.main import DotEnv
from pydantic import Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from mergecraft.config.env._base import EnvSettings, register_env_model

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic.fields import FieldInfo

__all__ = ["DotEnvFileSource", "LocalDotEnv", "local_dotenv_values"]


def local_dotenv_values(env_path: Path) -> dict[str, str]:
    """Return the raw string map of *env_path* through the shared ladder.

    The values are exactly what ``load_dotenv(override=False, encoding="utf-8")``
    would export: ``export`` prefixes are stripped, ``KEY=`` stays a present
    empty value, quotes are removed, inline comments are dropped, a bare key is
    discarded and ``${VAR}`` is interpolated. A missing file yields ``{}``.
    """
    parsed = DotEnv(env_path, encoding="utf-8", interpolate=True, override=False).dict()
    return {key: value for key, value in parsed.items() if value is not None}


def _first_alias(field: FieldInfo) -> str | None:
    """Return the first string env alias a field declares, or ``None``."""
    alias = field.validation_alias
    if isinstance(alias, str):
        return alias
    choices = getattr(alias, "choices", ())
    for choice in choices:
        if isinstance(choice, str):
            return choice
    return None


class DotEnvFileSource(PydanticBaseSettingsSource):
    """Yield the values of one ``.env`` file, ignoring the environment."""

    def __init__(self, settings_cls: type[BaseSettings], env_path: Path) -> None:
        super().__init__(settings_cls)
        self._env_path = env_path

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        # Per-field lookup is unused: the whole file is read once in ``__call__``.
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        return dict(local_dotenv_values(self._env_path))


class LocalDotEnv(EnvSettings):
    """The typed view of a local ``.env`` file.

    Only the file feeds this model. ``MERGECRAFT_ENV`` and the ``.env``-resident
    secrets are declared fields with exact variable names; every other key is
    kept as an extra so a reader can reproduce the whole file. A missing path
    construction (``LocalDotEnv()``) reads nothing.
    """

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="allow",
        env_ignore_empty=False,
    )

    _dotenv_path: ClassVar[Path | None] = None

    MERGECRAFT_ENV: str | None = Field(default=None, validation_alias="MERGECRAFT_ENV")
    MERGECRAFT_LOGFIRE_TOKEN: SecretStr | None = Field(
        default=None, validation_alias="MERGECRAFT_LOGFIRE_TOKEN"
    )
    TYPESAFE_API_KEY: SecretStr | None = Field(default=None, validation_alias="TYPESAFE_API_KEY")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Read only the file named on the class, or nothing when unnamed."""
        env_path = getattr(settings_cls, "_dotenv_path", None)
        if env_path is None:
            return ()
        return (DotEnvFileSource(settings_cls, env_path),)

    @classmethod
    def from_file(cls, env_path: Path) -> LocalDotEnv:
        """Parse *env_path* through this model; a missing file yields defaults."""
        # ``type()`` cannot be typed statically; the cast names the bound subclass.
        bound = cast(
            "type[LocalDotEnv]",
            type(f"{cls.__name__}AtPath", (cls,), {"_dotenv_path": env_path}),
        )
        return bound()

    def raw_values(self) -> dict[str, str]:
        """Return the file's keys and raw string values, secrets unwrapped."""
        values: dict[str, str] = {}
        for name, field in type(self).model_fields.items():
            value = getattr(self, name, None)
            if value is None:
                continue
            key = _first_alias(field) or name
            values[key] = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
        for key, value in (self.model_extra or {}).items():
            values[key] = "" if value is None else str(value)
        return values


register_env_model(LocalDotEnv)
