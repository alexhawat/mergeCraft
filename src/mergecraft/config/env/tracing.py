"""Typed environment model for the tracing family.

Every ``MERGECRAFT_TRACING*`` / ``MERGECRAFT_LOGFIRE_TOKEN`` /
``MERGECRAFT_OTEL_ENDPOINT`` / ``MERGECRAFT_TRACE_DIR`` read goes through
:class:`TracingEnv`, so one module owns the parse and the vocabulary. The model
does **not** change what a value means for a well-formed value: the resolvers
keep their precedence arithmetic and read the fields this model produces.

Four variables carry a control and therefore **fail closed** (a non-empty
unknown value raises :class:`~mergecraft.config.env.EnvSettingsError` instead of
being ignored, which would let a lower layer's more permissive value win):

* ``MERGECRAFT_TRACING`` — the enable flag;
* ``MERGECRAFT_TRACING_REGION`` — ``us`` / ``eu``;
* ``MERGECRAFT_TRACING_CONTENT`` — ``off`` / ``metadata`` / ``redacted`` / ``full``;
* ``MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT`` — the untrusted-body opt-in.

An **empty** value on any of them stays "no opinion" (today's behaviour).

``env_ignore_empty`` is ``False`` here because the resolvers treat
``"MERGECRAFT_TRACING_TO" in env`` (an empty value) as *present*: the model must
keep the difference between "absent" and "present but empty" so the precedence
arithmetic stays byte-for-byte.

The package is a leaf (see :mod:`mergecraft.config.env`); this module imports
``pydantic`` and the package itself and nothing else.
"""

from __future__ import annotations

from typing import Annotated, Any, Final

from pydantic import BeforeValidator, Field, SecretStr
from pydantic_settings import SettingsConfigDict

from mergecraft.config.env._base import (
    EnvSettings,
    EnvSettingsError,
    fail_closed_env_bool,
    register_env_model,
)

__all__ = ["TracingEnv"]

_VALID_REGIONS: Final[frozenset[str]] = frozenset({"us", "eu"})
_VALID_CONTENT_LEVELS: Final[frozenset[str]] = frozenset({"off", "metadata", "redacted", "full"})


def _validate_tracing_enabled(value: Any) -> bool | None:
    """The enable flag: ``EnvBool`` semantics, fail closed on a typo."""
    return fail_closed_env_bool("MERGECRAFT_TRACING", value)


def _validate_export_untrusted_content(value: Any) -> bool | None:
    """The untrusted-body opt-in: ``EnvBool`` semantics, fail closed on a typo."""
    return fail_closed_env_bool("MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT", value)


def _validate_region(value: Any) -> str | None:
    """Strip and lower the region; ``us`` / ``eu`` only, fail closed otherwise."""
    if value is None:
        return None
    region = str(value).strip().lower()
    if not region:
        return None
    if region not in _VALID_REGIONS:
        raise EnvSettingsError("MERGECRAFT_TRACING_REGION")
    return region


def _validate_content(value: Any) -> str | None:
    """Validate the capture level, keeping the stripped spelling today's layer used."""
    if value is None:
        return None
    content = str(value).strip()
    if not content:
        return None
    if content.lower() not in _VALID_CONTENT_LEVELS:
        raise EnvSettingsError("MERGECRAFT_TRACING_CONTENT")
    return content


def _strip_or_none(value: Any) -> str | None:
    """Strip a free-form value; empty and whitespace-only become "absent"."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@register_env_model
class TracingEnv(EnvSettings):
    """The tracing environment: exact variable names, no widening.

    Each field declares its variable with ``validation_alias``; ``extra`` is
    ignored and the names are exact (``case_sensitive``). Constructed per read
    (no cache), so a value written to ``os.environ`` mid-run is seen by the next
    read.
    """

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        env_ignore_empty=False,
    )

    tracing_enabled: Annotated[bool | None, BeforeValidator(_validate_tracing_enabled)] = Field(
        default=None, validation_alias="MERGECRAFT_TRACING"
    )
    tracing_to: str | None = Field(default=None, validation_alias="MERGECRAFT_TRACING_TO")
    trace_dir: str | None = Field(default=None, validation_alias="MERGECRAFT_TRACE_DIR")
    logfire_token: SecretStr | None = Field(
        default=None, validation_alias="MERGECRAFT_LOGFIRE_TOKEN"
    )
    otel_endpoint: str | None = Field(default=None, validation_alias="MERGECRAFT_OTEL_ENDPOINT")
    tracing_project: Annotated[str | None, BeforeValidator(_strip_or_none)] = Field(
        default=None, validation_alias="MERGECRAFT_TRACING_PROJECT"
    )
    tracing_region: Annotated[str | None, BeforeValidator(_validate_region)] = Field(
        default=None, validation_alias="MERGECRAFT_TRACING_REGION"
    )
    tracing_content: Annotated[str | None, BeforeValidator(_validate_content)] = Field(
        default=None, validation_alias="MERGECRAFT_TRACING_CONTENT"
    )
    export_untrusted_content: Annotated[
        bool | None, BeforeValidator(_validate_export_untrusted_content)
    ] = Field(default=None, validation_alias="MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT")
