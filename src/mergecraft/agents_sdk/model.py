"""Model and OpenAI-compatible client resolution for Agents SDK review."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mergecraft.agents.openai_compatible_gateways import (
    CUSTOM_PROVIDER_API_KEY_ENV,
    CUSTOM_PROVIDER_BASE_URL_ENV,
    resolve_gateway_endpoint,
)

if TYPE_CHECKING:
    from agents.models.interface import Model
    from openai import AsyncOpenAI

OPENCODE_GO_API_KEY_ENV = "OPENCODE_GO_API_KEY"
OPENCODE_ZEN_BASE_URL = "https://opencode.ai/zen/v1"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OPENCODE_GO_MODEL = "opencode-go/deepseek-v4.1-flash"


@dataclass(frozen=True, slots=True)
class AgentsSdkModelConfig:
    """OpenAI-compatible endpoint configuration for ``review_agent``."""

    model: str
    base_url: str | None
    api_key_env: str
    api_key: str

    def openai_model_name(self) -> str:
        """Model id sent to the OpenAI-compatible ``/chat/completions`` API."""
        slash = self.model.find("/")
        if slash <= 0:
            return self.model
        return self.model[slash + 1 :]


def _read_key(env_name: str) -> str | None:
    value = os.environ.get(env_name, "").strip()
    return value or None


def _custom_provider_env_pair_set() -> bool:
    return bool(_read_key(CUSTOM_PROVIDER_API_KEY_ENV) and _read_key(CUSTOM_PROVIDER_BASE_URL_ENV))


def _api_key_env_for_provider_id(provider_id: str) -> str:
    from mergecraft.config.runtime_provider_registry import lookup_registry_entry
    from mergecraft.config.settings_snapshot import repo_settings_for_gateway_resolvers

    entry = lookup_registry_entry(repo_settings_for_gateway_resolvers(), provider_id)
    if entry is not None:
        return f"LLM_PROVIDER_{entry.env_index}_API_KEY"
    return CUSTOM_PROVIDER_API_KEY_ENV


def resolve_model_config(
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    api_key_env: str | None = None,
) -> AgentsSdkModelConfig:
    """Resolve model + endpoint from explicit args, gateway registry, or env.

    Precedence:
    1. Explicit ``model``, ``base_url``, and ``api_key`` / ``api_key_env``.
    2. ``resolve_gateway_endpoint`` for ``provider/model`` slugs (registry or
       ``MERGECRAFT_CUSTOM_PROVIDER_*``).
    3. ``OPENAI_API_KEY`` with ``DEFAULT_OPENAI_MODEL``.
    4. ``OPENCODE_GO_API_KEY`` with OpenCode Zen base URL and
       ``DEFAULT_OPENCODE_GO_MODEL``.

    When only ``MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}`` are set, also set
    ``MERGECRAFT_AGENTS_SDK_MODEL`` to a ``provider/model-id`` slug (for example
    ``custom/my-model``).
    """
    if model and base_url and (api_key or api_key_env):
        key = api_key or (_read_key(api_key_env or "") or "")
        if not key:
            msg = f"{api_key_env or 'api_key'} is empty"
            raise ValueError(msg)
        return AgentsSdkModelConfig(
            model=model,
            base_url=base_url.rstrip("/"),
            api_key_env=api_key_env or CUSTOM_PROVIDER_API_KEY_ENV,
            api_key=key,
        )

    from mergecraft.config.env.agents import AgentRuntimeEnv

    runtime = AgentRuntimeEnv()
    slug = (model or runtime.agents_sdk_model or "").strip()
    if slug:
        endpoint = resolve_gateway_endpoint(slug)
        if endpoint is not None:
            provider_id, resolved_base, key = endpoint
            return AgentsSdkModelConfig(
                model=slug,
                base_url=resolved_base.rstrip("/"),
                api_key_env=_api_key_env_for_provider_id(provider_id),
                api_key=key,
            )

    if _custom_provider_env_pair_set():
        msg = (
            f"{CUSTOM_PROVIDER_API_KEY_ENV} and {CUSTOM_PROVIDER_BASE_URL_ENV} are set; "
            "also set MERGECRAFT_AGENTS_SDK_MODEL to a provider/model slug "
            "(for example custom/my-model)."
        )
        raise ValueError(msg)

    openai_key = api_key or _read_key(api_key_env or "OPENAI_API_KEY")
    if openai_key:
        resolved_model = slug or DEFAULT_OPENAI_MODEL
        return AgentsSdkModelConfig(
            model=resolved_model,
            base_url=base_url,
            api_key_env=api_key_env or "OPENAI_API_KEY",
            api_key=openai_key,
        )

    go_key = _read_key(OPENCODE_GO_API_KEY_ENV)
    if go_key:
        resolved_model = slug or DEFAULT_OPENCODE_GO_MODEL
        return AgentsSdkModelConfig(
            model=resolved_model,
            base_url=(base_url or OPENCODE_ZEN_BASE_URL).rstrip("/"),
            api_key_env=OPENCODE_GO_API_KEY_ENV,
            api_key=go_key,
        )

    msg = (
        "No model credentials found. Set OPENAI_API_KEY, OPENCODE_GO_API_KEY, "
        f"{CUSTOM_PROVIDER_API_KEY_ENV} and {CUSTOM_PROVIDER_BASE_URL_ENV} "
        "(with MERGECRAFT_AGENTS_SDK_MODEL), or pass api_key explicitly."
    )
    raise ValueError(msg)


def build_async_openai_client(config: AgentsSdkModelConfig) -> AsyncOpenAI:
    """Construct an ``AsyncOpenAI`` client for the resolved config."""
    from openai import AsyncOpenAI

    if config.base_url:
        return AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
    return AsyncOpenAI(api_key=config.api_key)


def agents_sdk_model_from_config(config: AgentsSdkModelConfig) -> Model:
    """Return an Agents SDK ``Model`` wired to ``config``."""
    from agents import OpenAIChatCompletionsModel

    client = build_async_openai_client(config)
    return OpenAIChatCompletionsModel(
        model=config.openai_model_name(),
        openai_client=client,
    )


__all__ = [
    "DEFAULT_OPENAI_MODEL",
    "DEFAULT_OPENCODE_GO_MODEL",
    "OPENCODE_GO_API_KEY_ENV",
    "OPENCODE_ZEN_BASE_URL",
    "AgentsSdkModelConfig",
    "agents_sdk_model_from_config",
    "build_async_openai_client",
    "resolve_model_config",
]
