"""Model alias registry (ported from mergecraft models.ts).

Slugs use the format ``provider/model-id`` (e.g. ``anthropic/claude-opus``).
Bump ``resolve`` when a new model generation ships — the alias (slug) stays stable.
"""

from __future__ import annotations

import re
from typing import Literal, TypeGuard

from pydantic import BaseModel, ConfigDict

ModelRouting = Literal["bedrock", "vertex"]


class ModelAlias(BaseModel):
    """Flat alias entry derived from the provider catalog."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    provider: str
    display_name: str
    description: str | None = None
    resolve: str
    open_router_resolve: str | None = None
    preferred: bool = False
    is_free: bool = False
    fallback: str | None = None
    routing: ModelRouting | None = None
    subagent_model: str | None = None
    hidden: bool = False


class ModelDef(BaseModel):
    """Per-model definition nested under a provider."""

    model_config = ConfigDict(extra="forbid")

    display_name: str
    description: str | None = None
    resolve: str
    open_router_resolve: str | None = None
    preferred: bool = False
    env_vars: tuple[str, ...] | None = None
    is_free: bool = False
    fallback: str | None = None
    routing: ModelRouting | None = None
    subagent_model: str | None = None
    hidden: bool = False


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str
    env_vars: tuple[str, ...]
    managed_credentials: tuple[str, ...] = ()
    models: dict[str, ModelDef]


def _provider(config: ProviderConfig) -> ProviderConfig:
    return config


PROVIDERS: dict[str, ProviderConfig] = {
    "anthropic": _provider(
        ProviderConfig(
            display_name="Anthropic",
            env_vars=("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"),
            models={
                "claude-fable": ModelDef(
                    display_name="Claude Fable",
                    resolve="anthropic/claude-fable-5",
                    open_router_resolve="openrouter/~anthropic/claude-fable-latest",
                    subagent_model="claude-sonnet",
                ),
                "claude-opus": ModelDef(
                    display_name="Claude Opus",
                    resolve="anthropic/claude-opus-4-8",
                    open_router_resolve="openrouter/anthropic/claude-opus-4.8",
                    preferred=True,
                    subagent_model="claude-sonnet",
                ),
                "claude-sonnet": ModelDef(
                    display_name="Claude Sonnet",
                    resolve="anthropic/claude-sonnet-5",
                    open_router_resolve="openrouter/anthropic/claude-sonnet-5",
                ),
                "claude-haiku": ModelDef(
                    display_name="Claude Haiku",
                    resolve="anthropic/claude-haiku-4-5",
                    open_router_resolve="openrouter/anthropic/claude-haiku-4.5",
                ),
            },
        )
    ),
    "openai": _provider(
        ProviderConfig(
            display_name="OpenAI",
            env_vars=("OPENAI_API_KEY",),
            managed_credentials=("CODEX_AUTH_JSON",),
            models={
                "gpt": ModelDef(
                    display_name="GPT Sol",
                    resolve="openai/gpt-5.6-sol",
                    open_router_resolve="openrouter/openai/gpt-5.6-sol",
                    preferred=True,
                    subagent_model="gpt-terra",
                ),
                "gpt-pro": ModelDef(
                    display_name="GPT Sol Pro",
                    description="Maximum reasoning effort",
                    resolve="openai/gpt-5.6-sol",
                    open_router_resolve="openrouter/openai/gpt-5.6-sol-pro",
                    subagent_model="gpt",
                ),
                "gpt-terra": ModelDef(
                    display_name="GPT Terra",
                    resolve="openai/gpt-5.6-terra",
                    open_router_resolve="openrouter/openai/gpt-5.6-terra",
                ),
                "gpt-mini": ModelDef(
                    display_name="GPT Luna",
                    resolve="openai/gpt-5.6-luna",
                    open_router_resolve="openrouter/openai/gpt-5.6-luna",
                ),
                "gpt-codex": ModelDef(
                    display_name="GPT Codex",
                    resolve="openai/gpt-5.3-codex",
                    open_router_resolve="openrouter/openai/gpt-5.3-codex",
                    fallback="openai/gpt",
                ),
                "gpt-codex-mini": ModelDef(
                    display_name="GPT Codex Mini",
                    resolve="openai/gpt-5.1-codex-mini",
                    open_router_resolve="openrouter/openai/gpt-5.1-codex-mini",
                    fallback="openai/gpt-mini",
                ),
                "gpt-5.4": ModelDef(
                    display_name="GPT 5.4",
                    resolve="openai/gpt-5.4",
                    open_router_resolve="openrouter/openai/gpt-5.4",
                    fallback="openai/gpt",
                ),
                "o3": ModelDef(
                    display_name="O3",
                    resolve="openai/o3",
                    open_router_resolve="openrouter/openai/o3",
                ),
            },
        )
    ),
    "google": _provider(
        ProviderConfig(
            display_name="Google",
            env_vars=("GEMINI_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY"),
            models={
                "gemini-pro": ModelDef(
                    display_name="Gemini Pro",
                    resolve="google/gemini-3.1-pro-preview",
                    open_router_resolve="openrouter/google/gemini-3.1-pro-preview",
                    preferred=True,
                ),
                "gemini-flash": ModelDef(
                    display_name="Gemini Flash",
                    resolve="google/gemini-3.5-flash",
                    open_router_resolve="openrouter/google/gemini-3.5-flash",
                ),
            },
        )
    ),
    "xai": _provider(
        ProviderConfig(
            display_name="xAI",
            env_vars=("XAI_API_KEY",),
            models={
                "grok": ModelDef(
                    display_name="Grok",
                    resolve="xai/grok-4.3",
                    open_router_resolve="openrouter/x-ai/grok-4.3",
                    preferred=True,
                ),
                "grok-fast": ModelDef(
                    display_name="Grok Fast",
                    resolve="xai/grok-4-1-fast",
                    open_router_resolve="openrouter/x-ai/grok-4.3",
                    fallback="xai/grok",
                ),
                "grok-code-fast": ModelDef(
                    display_name="Grok Code Fast",
                    resolve="xai/grok-code-fast-1",
                    open_router_resolve="openrouter/x-ai/grok-4.3",
                    fallback="xai/grok",
                ),
            },
        )
    ),
    "deepseek": _provider(
        ProviderConfig(
            display_name="DeepSeek",
            env_vars=("DEEPSEEK_API_KEY",),
            models={
                "deepseek-pro": ModelDef(
                    display_name="DeepSeek Pro",
                    resolve="deepseek/deepseek-v4-pro",
                    open_router_resolve="openrouter/deepseek/deepseek-v4-pro",
                    preferred=True,
                ),
                "deepseek-flash": ModelDef(
                    display_name="DeepSeek Flash",
                    resolve="deepseek/deepseek-v4-flash",
                    open_router_resolve="openrouter/deepseek/deepseek-v4-flash",
                ),
                "deepseek-reasoner": ModelDef(
                    display_name="DeepSeek Reasoner",
                    resolve="deepseek/deepseek-reasoner",
                    open_router_resolve="openrouter/deepseek/deepseek-v3.2",
                    fallback="deepseek/deepseek-pro",
                ),
                "deepseek-chat": ModelDef(
                    display_name="DeepSeek Chat",
                    resolve="deepseek/deepseek-chat",
                    open_router_resolve="openrouter/deepseek/deepseek-v3.2",
                    fallback="deepseek/deepseek-flash",
                ),
            },
        )
    ),
    "moonshotai": _provider(
        ProviderConfig(
            display_name="Moonshot AI",
            env_vars=("MOONSHOT_API_KEY",),
            models={
                "kimi-k2": ModelDef(
                    display_name="Kimi K2",
                    resolve="moonshotai/kimi-k2.7-code",
                    open_router_resolve="openrouter/moonshotai/kimi-k2.7-code",
                    preferred=True,
                ),
            },
        )
    ),
    "opencode": _provider(
        ProviderConfig(
            display_name="OpenCode",
            env_vars=("OPENCODE_API_KEY",),
            models={
                "big-pickle": ModelDef(
                    display_name="Big Pickle",
                    resolve="opencode/big-pickle",
                    preferred=True,
                    env_vars=(),
                    is_free=True,
                ),
                "claude-opus": ModelDef(
                    display_name="Claude Opus",
                    resolve="opencode/claude-opus-4-8",
                    open_router_resolve="openrouter/anthropic/claude-opus-4.8",
                    subagent_model="claude-sonnet",
                ),
                "claude-sonnet": ModelDef(
                    display_name="Claude Sonnet",
                    resolve="opencode/claude-sonnet-5",
                    open_router_resolve="openrouter/anthropic/claude-sonnet-5",
                ),
                "claude-haiku": ModelDef(
                    display_name="Claude Haiku",
                    resolve="opencode/claude-haiku-4-5",
                    open_router_resolve="openrouter/anthropic/claude-haiku-4.5",
                ),
                "gpt": ModelDef(
                    display_name="GPT Sol",
                    resolve="opencode/gpt-5.6-sol",
                    open_router_resolve="openrouter/openai/gpt-5.6-sol",
                    subagent_model="gpt-terra",
                ),
                "gpt-pro": ModelDef(
                    display_name="GPT Sol Pro",
                    description="Maximum reasoning effort",
                    resolve="opencode/gpt-5.6-sol",
                    open_router_resolve="openrouter/openai/gpt-5.6-sol-pro",
                    subagent_model="gpt",
                ),
                "gpt-terra": ModelDef(
                    display_name="GPT Terra",
                    resolve="opencode/gpt-5.6-terra",
                    open_router_resolve="openrouter/openai/gpt-5.6-terra",
                ),
                "gpt-mini": ModelDef(
                    display_name="GPT Luna",
                    resolve="opencode/gpt-5.6-luna",
                    open_router_resolve="openrouter/openai/gpt-5.6-luna",
                ),
                "gpt-codex": ModelDef(
                    display_name="GPT Codex",
                    resolve="opencode/gpt-5.3-codex",
                    open_router_resolve="openrouter/openai/gpt-5.3-codex",
                    fallback="opencode/gpt",
                ),
                "gpt-codex-mini": ModelDef(
                    display_name="GPT Codex Mini",
                    resolve="opencode/gpt-5.1-codex-mini",
                    open_router_resolve="openrouter/openai/gpt-5.1-codex-mini",
                    fallback="opencode/gpt-mini",
                ),
                "gpt-5.4": ModelDef(
                    display_name="GPT 5.4",
                    resolve="opencode/gpt-5.4",
                    open_router_resolve="openrouter/openai/gpt-5.4",
                    fallback="opencode/gpt",
                ),
                "gemini-pro": ModelDef(
                    display_name="Gemini Pro",
                    resolve="opencode/gemini-3.1-pro",
                    open_router_resolve="openrouter/google/gemini-3.1-pro-preview",
                ),
                "gemini-flash": ModelDef(
                    display_name="Gemini Flash",
                    resolve="opencode/gemini-3.5-flash",
                    open_router_resolve="openrouter/google/gemini-3.5-flash",
                ),
                "kimi-k2": ModelDef(
                    display_name="Kimi K2",
                    resolve="opencode/kimi-k2.6",
                    open_router_resolve="openrouter/moonshotai/kimi-k2.7-code",
                ),
                "minimax-m2.5": ModelDef(
                    display_name="MiniMax M2",
                    resolve="opencode/minimax-m2.5",
                    open_router_resolve="openrouter/minimax/minimax-m2.5",
                ),
                "gpt-5-nano": ModelDef(
                    display_name="GPT Nano",
                    resolve="opencode/gpt-5-nano",
                    open_router_resolve="openrouter/openai/gpt-5-nano",
                ),
                "mimo-v2-pro-free": ModelDef(
                    display_name="MiMo V2 Pro",
                    resolve="opencode/mimo-v2-pro-free",
                    env_vars=(),
                    is_free=True,
                    fallback="opencode/big-pickle",
                ),
                "minimax-m2.5-free": ModelDef(
                    display_name="MiniMax M2",
                    resolve="opencode/minimax-m2.5-free",
                    env_vars=(),
                    is_free=True,
                    fallback="opencode/big-pickle",
                    hidden=True,
                ),
            },
        )
    ),
    "opencode-go": _provider(
        ProviderConfig(
            display_name="OpenCode Go",
            env_vars=("OPENCODE_API_KEY",),
            models={
                "glm-5.1": ModelDef(
                    display_name="GLM 5.1",
                    resolve="opencode-go/glm-5.2",
                    open_router_resolve="openrouter/z-ai/glm-5.2",
                    preferred=True,
                ),
                "kimi-k2": ModelDef(
                    display_name="Kimi K2",
                    resolve="opencode-go/kimi-k2.7-code",
                    open_router_resolve="openrouter/moonshotai/kimi-k2.7-code",
                ),
            },
        )
    ),
    "bedrock": _provider(
        ProviderConfig(
            display_name="Amazon Bedrock",
            env_vars=("AWS_BEARER_TOKEN_BEDROCK", "AWS_REGION", "BEDROCK_MODEL_ID"),
            models={
                "byok": ModelDef(
                    display_name="Amazon Bedrock",
                    resolve="bedrock",
                    routing="bedrock",
                ),
            },
        )
    ),
    "vertex": _provider(
        ProviderConfig(
            display_name="Google Vertex AI",
            env_vars=(
                "VERTEX_SERVICE_ACCOUNT_JSON",
                "GOOGLE_CLOUD_PROJECT",
                "VERTEX_LOCATION",
                "VERTEX_MODEL_ID",
            ),
            models={
                "byok": ModelDef(
                    display_name="Google Vertex AI",
                    resolve="vertex",
                    routing="vertex",
                ),
            },
        )
    ),
    "nous": _provider(
        ProviderConfig(
            display_name="Nous Portal",
            env_vars=("NOUS_API_KEY",),
            models={
                "deepseek-v4-flash": ModelDef(
                    display_name="DeepSeek V4 Flash (Nous)",
                    description=(
                        "DeepSeek V4 Flash via the Nous Portal OpenAI-compatible endpoint. "
                        "Pass as nous/deepseek/deepseek-v4-flash for the portal model id."
                    ),
                    resolve="nous/deepseek/deepseek-v4-flash",
                    preferred=True,
                ),
                "deepseek/deepseek-v4-flash": ModelDef(
                    display_name="DeepSeek V4 Flash",
                    resolve="nous/deepseek/deepseek-v4-flash",
                    preferred=True,
                    hidden=True,
                ),
            },
        )
    ),
    "tokenhub": _provider(
        ProviderConfig(
            display_name="Tencent TokenHub",
            env_vars=("TOKENHUB_API_KEY",),
            models={
                "hy3": ModelDef(
                    display_name="Hy3",
                    description="Tencent Hunyuan Hy3 via TokenHub (OpenAI-compatible).",
                    resolve="tokenhub/hy3",
                    preferred=True,
                ),
                "deepseek-v4-flash": ModelDef(
                    display_name="DeepSeek V4 Flash (TokenHub)",
                    resolve="tokenhub/deepseek-v4-flash",
                ),
                "deepseek-v4-pro": ModelDef(
                    display_name="DeepSeek V4 Pro (TokenHub)",
                    resolve="tokenhub/deepseek-v4-pro",
                ),
                "glm-5.2": ModelDef(
                    display_name="GLM 5.2 (TokenHub)",
                    resolve="tokenhub/glm-5.2",
                ),
                "kimi-k3": ModelDef(
                    display_name="Kimi K3 (TokenHub)",
                    resolve="tokenhub/kimi-k3",
                ),
            },
        )
    ),
    "openrouter": _provider(
        ProviderConfig(
            display_name="OpenRouter",
            env_vars=("OPENROUTER_API_KEY",),
            models={
                "claude-opus": ModelDef(
                    display_name="Claude Opus",
                    resolve="openrouter/~anthropic/claude-opus-latest",
                    open_router_resolve="openrouter/~anthropic/claude-opus-latest",
                    preferred=True,
                    subagent_model="claude-sonnet",
                ),
                "claude-sonnet": ModelDef(
                    display_name="Claude Sonnet",
                    resolve="openrouter/~anthropic/claude-sonnet-latest",
                    open_router_resolve="openrouter/~anthropic/claude-sonnet-latest",
                ),
                "claude-haiku": ModelDef(
                    display_name="Claude Haiku",
                    resolve="openrouter/~anthropic/claude-haiku-latest",
                    open_router_resolve="openrouter/~anthropic/claude-haiku-latest",
                ),
                "gpt": ModelDef(
                    display_name="GPT Sol",
                    resolve="openrouter/openai/gpt-5.6-sol",
                    open_router_resolve="openrouter/openai/gpt-5.6-sol",
                    subagent_model="gpt-terra",
                ),
                "gpt-pro": ModelDef(
                    display_name="GPT Sol Pro",
                    description="Maximum reasoning effort",
                    resolve="openrouter/openai/gpt-5.6-sol-pro",
                    open_router_resolve="openrouter/openai/gpt-5.6-sol-pro",
                    subagent_model="gpt",
                ),
                "gpt-terra": ModelDef(
                    display_name="GPT Terra",
                    resolve="openrouter/openai/gpt-5.6-terra",
                    open_router_resolve="openrouter/openai/gpt-5.6-terra",
                ),
                "gpt-mini": ModelDef(
                    display_name="GPT Luna",
                    resolve="openrouter/openai/gpt-5.6-luna",
                    open_router_resolve="openrouter/openai/gpt-5.6-luna",
                ),
                "gpt-codex": ModelDef(
                    display_name="GPT Codex",
                    resolve="openrouter/openai/gpt-5.3-codex",
                    open_router_resolve="openrouter/openai/gpt-5.3-codex",
                    fallback="openrouter/gpt",
                ),
                "gpt-codex-mini": ModelDef(
                    display_name="GPT Codex Mini",
                    resolve="openrouter/openai/gpt-5.1-codex-mini",
                    open_router_resolve="openrouter/openai/gpt-5.1-codex-mini",
                    fallback="openrouter/gpt-mini",
                ),
                "gpt-5.4": ModelDef(
                    display_name="GPT 5.4",
                    resolve="openrouter/openai/gpt-5.4",
                    open_router_resolve="openrouter/openai/gpt-5.4",
                    fallback="openrouter/gpt",
                ),
                "o4-mini": ModelDef(
                    display_name="O4 Mini",
                    resolve="openrouter/openai/o4-mini",
                    open_router_resolve="openrouter/openai/o4-mini",
                ),
                "gemini-pro": ModelDef(
                    display_name="Gemini Pro",
                    resolve="openrouter/~google/gemini-pro-latest",
                    open_router_resolve="openrouter/~google/gemini-pro-latest",
                ),
                "gemini-flash": ModelDef(
                    display_name="Gemini Flash",
                    resolve="openrouter/~google/gemini-flash-latest",
                    open_router_resolve="openrouter/~google/gemini-flash-latest",
                ),
                "grok": ModelDef(
                    display_name="Grok",
                    resolve="openrouter/x-ai/grok-4.3",
                    open_router_resolve="openrouter/x-ai/grok-4.3",
                ),
                "deepseek-pro": ModelDef(
                    display_name="DeepSeek Pro",
                    resolve="openrouter/deepseek/deepseek-v4-pro",
                    open_router_resolve="openrouter/deepseek/deepseek-v4-pro",
                ),
                "deepseek-flash": ModelDef(
                    display_name="DeepSeek Flash",
                    resolve="openrouter/deepseek/deepseek-v4-flash",
                    open_router_resolve="openrouter/deepseek/deepseek-v4-flash",
                ),
                "deepseek-chat": ModelDef(
                    display_name="DeepSeek Chat",
                    resolve="openrouter/deepseek/deepseek-v3.2",
                    open_router_resolve="openrouter/deepseek/deepseek-v3.2",
                    fallback="openrouter/deepseek-flash",
                ),
                "kimi-k2": ModelDef(
                    display_name="Kimi K2",
                    resolve="openrouter/moonshotai/kimi-k2.7-code",
                    open_router_resolve="openrouter/moonshotai/kimi-k2.7-code",
                ),
                "minimax-m2.5": ModelDef(
                    display_name="MiniMax M2",
                    resolve="openrouter/minimax/minimax-m2.5",
                    open_router_resolve="openrouter/minimax/minimax-m2.5",
                ),
            },
        )
    ),
}

# Back-compat lowercase alias matching TS `providers` export.
providers = PROVIDERS

ModelProvider = str  # dynamic keys of PROVIDERS


# ── slug parsing ───────────────────────────────────────────────────────────────


def parse_model(slug: str) -> tuple[str, str]:
    slash_idx = slug.find("/")
    if slash_idx == -1:
        msg = f'invalid model slug "{slug}" — expected "provider/model"'
        raise ValueError(msg)
    return slug[:slash_idx], slug[slash_idx + 1 :]


def get_model_provider(slug: str) -> str:
    return parse_model(slug)[0]


def get_provider_display_name(slug: str) -> str | None:
    provider_key, _ = parse_model(slug)
    config = PROVIDERS.get(provider_key)
    return config.display_name if config else None


def get_model_env_vars(slug: str) -> list[str]:
    provider_key, model_id = parse_model(slug)
    provider_config = PROVIDERS.get(provider_key)
    if provider_config is None:
        return []
    model_config = provider_config.models.get(model_id)
    if model_config is not None and model_config.env_vars is not None:
        return list(model_config.env_vars)
    return list(provider_config.env_vars)


def get_model_managed_credentials(slug: str) -> list[str]:
    provider_key, _ = parse_model(slug)
    provider_config = PROVIDERS.get(provider_key)
    if provider_config is None:
        return []
    return list(provider_config.managed_credentials)


# ── derived flat list ──────────────────────────────────────────────────────────


def _build_model_aliases() -> list[ModelAlias]:
    aliases: list[ModelAlias] = []
    for provider_key, config in PROVIDERS.items():
        for model_id, defn in config.models.items():
            aliases.append(
                ModelAlias(
                    slug=f"{provider_key}/{model_id}",
                    provider=provider_key,
                    display_name=defn.display_name,
                    description=defn.description,
                    resolve=defn.resolve,
                    open_router_resolve=defn.open_router_resolve,
                    preferred=defn.preferred,
                    is_free=defn.is_free,
                    fallback=defn.fallback,
                    routing=defn.routing,
                    subagent_model=(
                        f"{provider_key}/{defn.subagent_model}" if defn.subagent_model else None
                    ),
                    hidden=defn.hidden,
                )
            )
    return aliases


MODEL_ALIASES: list[ModelAlias] = _build_model_aliases()
model_aliases = MODEL_ALIASES

# ── auto tiers ───────────────────────────────────────────────────────────────

AutoTier = Literal["auto/efficient", "auto/intelligent"]
AUTO_EFFICIENT: AutoTier = "auto/efficient"
AUTO_INTELLIGENT: AutoTier = "auto/intelligent"

_AUTO_TIER_TARGET: dict[str, str] = {
    AUTO_EFFICIENT: "moonshotai/kimi-k2",
    AUTO_INTELLIGENT: "anthropic/claude-opus",
}


def is_auto_tier(slug: str | None) -> TypeGuard[AutoTier]:
    return slug in (AUTO_EFFICIENT, AUTO_INTELLIGENT)


def default_auto_tier(*, has_card: bool) -> AutoTier:
    return AUTO_INTELLIGENT if has_card else AUTO_EFFICIENT


def resolve_auto_tier(*, model: str | None, has_card: bool) -> AutoTier:
    if not has_card:
        return AUTO_EFFICIENT
    if is_auto_tier(model):
        return model
    return default_auto_tier(has_card=has_card)


def is_card_gated_model(slug: str) -> bool:
    return resolve_openrouter_model(slug) is not None


# ── resolution ───────────────────────────────────────────────────────────────

_MAX_FALLBACK_DEPTH = 10


def resolve_model_slug(slug: str) -> str | None:
    for alias in MODEL_ALIASES:
        if alias.slug == slug:
            return alias.resolve
    return None


def resolve_display_alias(slug: str) -> ModelAlias | None:
    current = _AUTO_TIER_TARGET[slug] if is_auto_tier(slug) else slug
    visited: set[str] = set()
    for _ in range(_MAX_FALLBACK_DEPTH):
        if current in visited:
            return None
        visited.add(current)
        alias = next((a for a in MODEL_ALIASES if a.slug == current), None)
        if alias is None:
            return None
        if not alias.fallback:
            return alias
        current = alias.fallback
    return None


def resolve_cli_model(slug: str) -> str | None:
    alias = resolve_display_alias(slug)
    return alias.resolve if alias else None


def resolve_openrouter_model(slug: str) -> str | None:
    alias = resolve_display_alias(slug)
    return alias.open_router_resolve if alias else None


# ── default proxy model ──────────────────────────────────────────────────────

_default_proxy_alias = resolve_display_alias(AUTO_EFFICIENT)
if _default_proxy_alias is None or _default_proxy_alias.open_router_resolve is None:
    msg = f"DEFAULT_PROXY_MODEL: {AUTO_EFFICIENT} has no openRouterResolve"
    raise RuntimeError(msg)

DEFAULT_PROXY_MODEL = _default_proxy_alias.open_router_resolve
_default_proxy_display_name = _default_proxy_alias.display_name


def get_auto_select_hint_model() -> str:
    return _default_proxy_display_name


# ── bedrock / vertex routing ─────────────────────────────────────────────────

BEDROCK_MODEL_ID_ENV = "BEDROCK_MODEL_ID"
VERTEX_MODEL_ID_ENV = "VERTEX_MODEL_ID"


def is_bedrock_anthropic_id(bedrock_model_id: str) -> bool:
    return "anthropic" in re.split(r"[./:]", bedrock_model_id.lower())


def is_vertex_anthropic_id(vertex_model_id: str) -> bool:
    return bool(re.match(r"(?i)^claude-", vertex_model_id.strip()))
