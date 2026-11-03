"""Typed environment models for the agent runtime and the provider gateways.

:class:`AgentRuntimeEnv` owns the knobs every provider driver and the credential
broker share: the agent timeout (default ``3600`` seconds), the Codex home
parent, and the model/agent selection overrides. Every driver constructs the
model per read, so a value written to ``os.environ`` mid-run is seen by the next
read.

:class:`ProviderGatewayEnv` owns the singleton OpenAI-compatible gateway pair
plus the two ``extra_options`` JSON strings. The **indexed** multi-provider
slots (``MERGECRAFT_CUSTOM_PROVIDER_*_<N>``) stay dynamic reads: the index is
enumerated at runtime, not a fixed setting (PS-D1).

The package is a leaf (see :mod:`mergecraft.config.env`); this module imports
``pydantic`` and the package itself and nothing else.
"""

from __future__ import annotations

from typing import Annotated, Any, Final

from pydantic import BeforeValidator, Field, SecretStr
from pydantic_settings import SettingsConfigDict

from mergecraft.config.env._base import EnvSettings

__all__ = ["OTEL_PLUGIN_ENV", "AgentRuntimeEnv", "ProviderGatewayEnv"]

#: The OpenCode OTel plugin opt-in variable. The name lives beside the model
#: that parses it; ``mergecraft.agents.opencode_otel`` re-exports it so callers
#: keep naming the variable symbolically.
OTEL_PLUGIN_ENV: Final[str] = "MERGECRAFT_OPENCODE_OTEL_PLUGIN"


def _strip_or_none(value: Any) -> Any:
    """Strip a free-form value; empty and whitespace-only become "absent"."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


_Stripped = Annotated[str | None, BeforeValidator(_strip_or_none)]


class AgentRuntimeEnv(EnvSettings):
    """The agent-runtime knobs: timeout, Codex home parent, model and agent."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        env_ignore_empty=True,
    )

    #: Seconds; today's drivers default to ``3600`` and a malformed value raises.
    agent_timeout: int = Field(default=3600, validation_alias="MERGECRAFT_AGENT_TIMEOUT")
    codex_home_parent: _Stripped = Field(
        default=None, validation_alias="MERGECRAFT_CODEX_HOME_PARENT"
    )
    model: _Stripped = Field(default=None, validation_alias="MERGECRAFT_MODEL")
    agent: _Stripped = Field(default=None, validation_alias="MERGECRAFT_AGENT")
    opencode_otel_plugin: _Stripped = Field(
        default=None, validation_alias="MERGECRAFT_OPENCODE_OTEL_PLUGIN"
    )


class ProviderGatewayEnv(EnvSettings):
    """The singleton custom-provider pair and the extra-options JSON strings."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        env_ignore_empty=True,
    )

    custom_provider_base_url: _Stripped = Field(
        default=None, validation_alias="MERGECRAFT_CUSTOM_PROVIDER_BASE_URL"
    )
    custom_provider_api_key: SecretStr | None = Field(
        default=None, validation_alias="MERGECRAFT_CUSTOM_PROVIDER_API_KEY"
    )
    custom_provider_extra_options: _Stripped = Field(
        default=None, validation_alias="MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS"
    )
    provider_extra_options: _Stripped = Field(
        default=None, validation_alias="MERGECRAFT_PROVIDER_EXTRA_OPTIONS"
    )
