"""Typed environment model for the Action ``INPUT_*`` settings.

Every input ``action.yml`` maps into the container environment except the GitHub
token is a field here: the tracing family (``INPUT_TRACING*``) plus the prompt,
setup, permission and provider inputs. ``INPUT_TOKEN`` is deliberately **not** a
field — it belongs to the ordered credential chain in
:mod:`mergecraft.utils.token` (PS-D12), and a second holder of the token buys no
validation.

The GitHub Actions runtime injects an **empty string** for an unset input, so
``env_ignore_empty`` is ``True`` here and every field is ``str | None`` (the two
control-carrying booleans and the Logfire token excepted) — an empty value is
"unset", never a value. The plain string fields are stripped, so a padded
``with:`` value means what :func:`mergecraft.utils.payload.get_action_input`
already makes it mean.

Two control-carrying inputs (``INPUT_TRACING`` and
``INPUT_TRACING_EXPORT_UNTRUSTED_CONTENT``) fail closed: a non-empty unknown
value raises :class:`~mergecraft.config.env.EnvSettingsError` rather than
deferring to a more permissive lower layer. An unknown ``INPUT_TRACING_TO``
keeps raising where the shorthand is resolved (unchanged).

``INPUT_PROVIDER_API_KEY_ENV`` is a field; the variable it *names* stays a
dynamic read, because its name is chosen at runtime.

The package is a leaf (see :mod:`mergecraft.config.env`); this module imports
``pydantic`` and the package itself and nothing else.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BeforeValidator, Field, SecretStr
from pydantic_settings import SettingsConfigDict

from mergecraft.config.env._base import EnvSettings, fail_closed_env_bool

__all__ = ["ActionInputEnv"]


def _strip_or_none(value: Any) -> Any:
    """Strip a string input; an empty or whitespace-only value is "unset"."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


_StripOrNone = Annotated[str | None, BeforeValidator(_strip_or_none)]


def _validate_input_tracing(value: Any) -> bool | None:
    """``INPUT_TRACING``: ``EnvBool`` semantics, fail closed on a typo."""
    return fail_closed_env_bool("INPUT_TRACING", value)


def _validate_input_export_untrusted_content(value: Any) -> bool | None:
    """``INPUT_TRACING_EXPORT_UNTRUSTED_CONTENT``: fail closed on a typo."""
    return fail_closed_env_bool("INPUT_TRACING_EXPORT_UNTRUSTED_CONTENT", value)


class ActionInputEnv(EnvSettings):
    """The Action ``INPUT_*`` settings the orchestrator reads.

    Constructed per read (no cache), so a value written to ``os.environ``
    mid-run is seen by the next read. Only the declared inputs are read; every
    other ``INPUT_*`` name is ignored (the token chain and an input of a
    dispatching workflow are not settings of this action).
    """

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        env_ignore_empty=True,
    )

    # ── prompt / run shape ───────────────────────────────────────────────────
    prompt: _StripOrNone = Field(default=None, validation_alias="INPUT_PROMPT")
    prompt_file: _StripOrNone = Field(default=None, validation_alias="INPUT_PROMPT_FILE")
    timeout: _StripOrNone = Field(default=None, validation_alias="INPUT_TIMEOUT")
    cwd: _StripOrNone = Field(default=None, validation_alias="INPUT_CWD")
    output_schema: _StripOrNone = Field(default=None, validation_alias="INPUT_OUTPUT_SCHEMA")
    allow_pr_target_comments: _StripOrNone = Field(
        default=None, validation_alias="INPUT_ALLOW_PR_TARGET_COMMENTS"
    )

    # ── model selection and permissions ─────────────────────────────────────
    model: _StripOrNone = Field(default=None, validation_alias="INPUT_MODEL")
    model_pin: _StripOrNone = Field(default=None, validation_alias="INPUT_MODEL_PIN")
    push: _StripOrNone = Field(default=None, validation_alias="INPUT_PUSH")
    shell: _StripOrNone = Field(default=None, validation_alias="INPUT_SHELL")
    status_checks: _StripOrNone = Field(default=None, validation_alias="INPUT_STATUS_CHECKS")
    suggest_eval_add: _StripOrNone = Field(default=None, validation_alias="INPUT_SUGGEST_EVAL_ADD")

    # ── analyzers and setup ─────────────────────────────────────────────────
    analyzers: _StripOrNone = Field(default=None, validation_alias="INPUT_ANALYZERS")
    sarif_upload: _StripOrNone = Field(default=None, validation_alias="INPUT_SARIF_UPLOAD")
    setup_failure_policy: _StripOrNone = Field(
        default=None, validation_alias="INPUT_SETUP_FAILURE_POLICY"
    )
    setup_timeout: _StripOrNone = Field(default=None, validation_alias="INPUT_SETUP_TIMEOUT")

    # ── custom provider (the *name* here, the value stays dynamic) ──────────
    provider_base_url: _StripOrNone = Field(
        default=None, validation_alias="INPUT_PROVIDER_BASE_URL"
    )
    provider_api_key_env: _StripOrNone = Field(
        default=None, validation_alias="INPUT_PROVIDER_API_KEY_ENV"
    )

    # ── tracing ─────────────────────────────────────────────────────────────
    tracing_enabled: Annotated[bool | None, BeforeValidator(_validate_input_tracing)] = Field(
        default=None, validation_alias="INPUT_TRACING"
    )
    tracing_to: str | None = Field(default=None, validation_alias="INPUT_TRACING_TO")
    logfire_token: SecretStr | None = Field(default=None, validation_alias="INPUT_LOGFIRE_TOKEN")
    otel_endpoint: str | None = Field(default=None, validation_alias="INPUT_OTEL_ENDPOINT")
    tracing_content: str | None = Field(default=None, validation_alias="INPUT_TRACING_CONTENT")
    export_untrusted_content: Annotated[
        bool | None, BeforeValidator(_validate_input_export_untrusted_content)
    ] = Field(default=None, validation_alias="INPUT_TRACING_EXPORT_UNTRUSTED_CONTENT")
