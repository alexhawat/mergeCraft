"""Typed environment models for the config-file locator and the run budgets.

Two reads live here because they are the two places where a setting is an
*input to a resolver*, not a resolved value:

* :class:`ConfigLocatorEnv` owns ``MERGECRAFT_CONFIG``, the one variable that
  locates the repo YAML. An empty value means "absent" (the startup and layered
  loaders already treat it that way); a whitespace-only value stays *present but
  not a file*, so ``doctor`` keeps reporting it — a frozen quirk, not a bug.
* :class:`RunBoundsEnv` owns the eight numeric run-budget knobs. The model only
  parses; :func:`mergecraft.utils.run_bounds.resolve_run_bounds` keeps its merge
  arithmetic byte-for-byte, including the asymmetry between an integer ``0``
  (which falls through to the configured budget) and a float ``0`` (which is
  honoured).

A malformed numeric value surfaces as Pydantic's ``ValidationError`` — a
``ValueError`` — whose message names the variable. The package is a leaf (see
:mod:`mergecraft.config.env`); this module imports ``pydantic`` and the package
itself and nothing else.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BeforeValidator, Field
from pydantic_settings import SettingsConfigDict

from mergecraft.config.env._base import EnvSettings, register_env_model

__all__ = ["ConfigLocatorEnv", "RunBoundsEnv"]


def _blank_to_none(value: Any) -> Any:
    """Treat an empty or whitespace-only string as "absent", else leave it alone.

    A typed numeric field would reject ``"   "``; today's ``float()`` /
    ``int()`` helpers treated it as unset before parsing, and the frozen parity
    table requires that to hold. Anything else is handed to Pydantic unchanged
    so a malformed value still raises.
    """
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


@register_env_model
class ConfigLocatorEnv(EnvSettings):
    """The repo-config locator: one exact variable, no prefix arithmetic."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        env_ignore_empty=True,
    )

    config_path: str | None = Field(default=None, validation_alias="MERGECRAFT_CONFIG")


@register_env_model
class RunBoundsEnv(EnvSettings):
    """The eight numeric run-budget and timeout knobs, as ``None`` when unset."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        env_ignore_empty=True,
    )

    token_budget: Annotated[int | None, BeforeValidator(_blank_to_none)] = Field(
        default=None, validation_alias="MERGECRAFT_TOKEN_BUDGET"
    )
    cost_budget_usd: Annotated[float | None, BeforeValidator(_blank_to_none)] = Field(
        default=None, validation_alias="MERGECRAFT_COST_BUDGET_USD"
    )
    tool_call_budget: Annotated[int | None, BeforeValidator(_blank_to_none)] = Field(
        default=None, validation_alias="MERGECRAFT_TOOL_CALL_BUDGET"
    )
    max_diff_lines: Annotated[int | None, BeforeValidator(_blank_to_none)] = Field(
        default=None, validation_alias="MERGECRAFT_MAX_DIFF_LINES"
    )
    context_retrieval_timeout_s: Annotated[float | None, BeforeValidator(_blank_to_none)] = Field(
        default=None, validation_alias="MERGECRAFT_CONTEXT_RETRIEVAL_TIMEOUT_S"
    )
    run_timeout_s: Annotated[float | None, BeforeValidator(_blank_to_none)] = Field(
        default=None, validation_alias="MERGECRAFT_RUN_TIMEOUT_S"
    )
    external_operation_timeout_s: Annotated[float | None, BeforeValidator(_blank_to_none)] = Field(
        default=None, validation_alias="MERGECRAFT_EXTERNAL_OPERATION_TIMEOUT_S"
    )
    cache_max_bytes: Annotated[int | None, BeforeValidator(_blank_to_none)] = Field(
        default=None, validation_alias="MERGECRAFT_CACHE_MAX_BYTES"
    )
