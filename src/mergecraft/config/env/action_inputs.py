"""Typed environment model for the tracing ``INPUT_*`` Action inputs.

This is the tracing section of the Action-input model. It covers exactly the
six tracing inputs ``action.yml`` maps into the container environment
(``INPUT_TRACING``, ``INPUT_TRACING_TO``, ``INPUT_LOGFIRE_TOKEN``,
``INPUT_OTEL_ENDPOINT``, ``INPUT_TRACING_CONTENT``,
``INPUT_TRACING_EXPORT_UNTRUSTED_CONTENT``); the remaining inputs join the same
model separately.

The GitHub Actions runtime injects an **empty string** for an unset input, so
``env_ignore_empty`` is ``True`` here and every field is ``str | None`` — an
empty value is "unset", never a value. The two control-carrying inputs
(``INPUT_TRACING`` and ``INPUT_TRACING_EXPORT_UNTRUSTED_CONTENT``) fail closed:
a non-empty unknown value raises
:class:`~mergecraft.config.env.EnvSettingsError` rather than deferring to a more
permissive lower layer. An unknown ``INPUT_TRACING_TO`` keeps raising where the
shorthand is resolved (unchanged).

The package is a leaf (see :mod:`mergecraft.config.env`); this module imports
``pydantic`` and the package itself and nothing else.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BeforeValidator, Field
from pydantic_settings import SettingsConfigDict

from mergecraft.config.env._base import EnvSettings, fail_closed_env_bool

__all__ = ["ActionInputEnv"]


def _validate_input_tracing(value: Any) -> bool | None:
    """``INPUT_TRACING``: ``EnvBool`` semantics, fail closed on a typo."""
    return fail_closed_env_bool("INPUT_TRACING", value)


def _validate_input_export_untrusted_content(value: Any) -> bool | None:
    """``INPUT_TRACING_EXPORT_UNTRUSTED_CONTENT``: fail closed on a typo."""
    return fail_closed_env_bool("INPUT_TRACING_EXPORT_UNTRUSTED_CONTENT", value)


class ActionInputEnv(EnvSettings):
    """The Action ``INPUT_*`` settings the orchestrator reads.

    Constructed per read (no cache). Only the tracing section exists today; the
    remaining ``INPUT_*`` names join this model separately.
    """

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        env_ignore_empty=True,
    )

    tracing_enabled: Annotated[bool | None, BeforeValidator(_validate_input_tracing)] = Field(
        default=None, validation_alias="INPUT_TRACING"
    )
    tracing_to: str | None = Field(default=None, validation_alias="INPUT_TRACING_TO")
    logfire_token: str | None = Field(default=None, validation_alias="INPUT_LOGFIRE_TOKEN")
    otel_endpoint: str | None = Field(default=None, validation_alias="INPUT_OTEL_ENDPOINT")
    tracing_content: str | None = Field(default=None, validation_alias="INPUT_TRACING_CONTENT")
    export_untrusted_content: Annotated[
        bool | None, BeforeValidator(_validate_input_export_untrusted_content)
    ] = Field(default=None, validation_alias="INPUT_TRACING_EXPORT_UNTRUSTED_CONTENT")
