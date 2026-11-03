"""Typed environment models for the operational knobs in ``utils/``, ``cli/``, ``mcp/``.

These are the settings that shape process behaviour rather than a review:
logging, the interactive/agent-protocol session, the MCP server, and the
filesystem paths mergeCraft owns. Each model is constructed per read, so a value
written to ``os.environ`` mid-run is seen by the next read.

Fallbacks are expressed with :class:`~pydantic.AliasChoices` in today's order —
``MERGECRAFT_LOG_LEVEL`` before ``LOG_LEVEL``, ``MERGECRAFT_LOG_FORMAT`` before
``LOG_FORMAT`` — and an empty value means "absent".

The package is a leaf (see :mod:`mergecraft.config.env`); this module imports
``pydantic`` and the package itself and nothing else.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import AliasChoices, BeforeValidator, Field, SecretStr
from pydantic_settings import SettingsConfigDict

from mergecraft.config.env._base import EnvSettings, register_env_model

__all__ = ["CliSessionEnv", "LoggingEnv", "McpEnv", "PathsEnv", "ReviewEnv", "RunInputsEnv"]


def _strip_or_none(value: Any) -> Any:
    """Strip a free-form value; empty and whitespace-only become "absent"."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


_Stripped = Annotated[str | None, BeforeValidator(_strip_or_none)]


@register_env_model
class LoggingEnv(EnvSettings):
    """Log level and format, with the documented ``MERGECRAFT_*`` → bare order."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        env_ignore_empty=True,
        # ``AliasChoices`` is a dynamic alias; the pydantic mypy plugin wants a
        # name fallback alongside it. Field names never collide with these
        # variables, so allowing them changes no environment read.
        populate_by_name=True,
    )

    # Two exact fields rather than one ``AliasChoices``: the effective resolver
    # prefers ``MERGECRAFT_LOG_LEVEL`` but falls back to the bare ``LOG_LEVEL``
    # when the first is *invalid*, and an alias pair would stop at the first
    # present value. Keeping them apart preserves that fallback byte-for-byte.
    mergecraft_log_level: str | None = Field(default=None, validation_alias="MERGECRAFT_LOG_LEVEL")
    log_level: str | None = Field(default=None, validation_alias="LOG_LEVEL")
    log_format: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MERGECRAFT_LOG_FORMAT", "LOG_FORMAT"),
    )


@register_env_model
class CliSessionEnv(EnvSettings):
    """The CLI session switches and the consumer agent-protocol offer."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        env_ignore_empty=True,
    )

    noninteractive: str | None = Field(default=None, validation_alias="MERGECRAFT_NONINTERACTIVE")
    force_interactive: str | None = Field(
        default=None, validation_alias="MERGECRAFT_FORCE_INTERACTIVE"
    )
    agent_protocol: str | None = Field(default=None, validation_alias="MERGECRAFT_AGENT_PROTOCOL")


@register_env_model
class McpEnv(EnvSettings):
    """The MCP server port, bearer token and remote API base URL."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        env_ignore_empty=True,
    )

    mcp_port: str | None = Field(default=None, validation_alias="MERGECRAFT_MCP_PORT")
    mcp_token: SecretStr | None = Field(default=None, validation_alias="MERGECRAFT_MCP_TOKEN")
    api_url: str | None = Field(default=None, validation_alias="MERGECRAFT_API_URL")


@register_env_model
class PathsEnv(EnvSettings):
    """Filesystem roots mergeCraft owns.

    ``keep_tmp`` and ``evidence_dir`` keep their raw presence semantics (any
    non-empty value), so they are not stripped: ``MERGECRAFT_KEEP_TMP=0`` still
    keeps the temp tree, exactly as today.
    """

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        env_ignore_empty=True,
    )

    cache_dir: str | None = Field(default=None, validation_alias="MERGECRAFT_CACHE_DIR")
    temp_parent: _Stripped = Field(default=None, validation_alias="MERGECRAFT_TEMP_PARENT")
    audit_root: str | None = Field(default=None, validation_alias="MERGECRAFT_AUDIT_ROOT")
    evidence_dir: str | None = Field(default=None, validation_alias="MERGECRAFT_EVIDENCE_DIR")
    keep_tmp: str | None = Field(default=None, validation_alias="MERGECRAFT_KEEP_TMP")
    cdp_url: _Stripped = Field(default=None, validation_alias="MERGECRAFT_CDP_URL")


@register_env_model
class RunInputsEnv(EnvSettings):
    """Inputs the consumer workflow forwards into the run (analyzers, CI, build)."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        env_ignore_empty=True,
        # ``AliasChoices`` is a dynamic alias; the pydantic mypy plugin wants a
        # name fallback alongside it. Field names never collide with these
        # variables, so allowing them changes no environment read.
        populate_by_name=True,
    )

    analyzers: _Stripped = Field(default=None, validation_alias="MERGECRAFT_ANALYZERS")
    ci_wait_state: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MERGECRAFT_CI_WAIT_STATE", "CI_STATE"),
    )
    ci_failed_count: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MERGECRAFT_CI_FAILED_COUNT", "CI_FAILED_COUNT"),
    )
    action_sha: _Stripped = Field(default=None, validation_alias="MERGECRAFT_ACTION_SHA")
    build_commit: _Stripped = Field(default=None, validation_alias="MERGECRAFT_BUILD_COMMIT")
    permanent_current_decision: str | None = Field(
        default=None, validation_alias="MERGECRAFT_PERMANENT_CURRENT_DECISION"
    )


class ReviewEnv(EnvSettings):
    """Review-publication knobs read outside the review package's own settings."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        env_ignore_empty=True,
    )

    sticky_only_neutral: _Stripped = Field(
        default=None, validation_alias="MERGECRAFT_STICKY_ONLY_NEUTRAL"
    )
    capture_verdicts: _Stripped = Field(
        default=None, validation_alias="MERGECRAFT_CAPTURE_VERDICTS"
    )
    reviewer_bot_login: _Stripped = Field(
        default=None, validation_alias="MERGECRAFT_REVIEWER_BOT_LOGIN"
    )
