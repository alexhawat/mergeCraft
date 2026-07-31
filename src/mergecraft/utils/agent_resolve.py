"""Resolve model slug + agent implementation for a run."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from loguru import logger

from mergecraft.agents import agents, resolve_agent
from mergecraft.models import (
    BEDROCK_MODEL_ID_ENV,
    VERTEX_MODEL_ID_ENV,
    get_model_provider,
    is_bedrock_anthropic_id,
    is_vertex_anthropic_id,
    resolve_cli_model,
    resolve_display_alias,
)

if TYPE_CHECKING:
    from mergecraft.agents.shared import Agent


def _has_env(name: str) -> bool:
    val = os.environ.get(name)
    return isinstance(val, str) and len(val) > 0


def _has_claude_code_auth() -> bool:
    return _has_env("CLAUDE_CODE_OAUTH_TOKEN") or _has_env("ANTHROPIC_API_KEY")


def _has_bedrock_auth() -> bool:
    return _has_env("AWS_BEARER_TOKEN_BEDROCK") or (
        _has_env("AWS_ACCESS_KEY_ID") and _has_env("AWS_SECRET_ACCESS_KEY")
    )


def _has_vertex_auth() -> bool:
    return _has_env("GOOGLE_APPLICATION_CREDENTIALS") or _has_env("VERTEX_SERVICE_ACCOUNT_JSON")


def _has_codex_subscription_auth() -> bool:
    return _has_env("CODEX_AUTH_JSON")


def _has_openai_api_key_auth() -> bool:
    return _has_env("OPENAI_API_KEY")


def _has_gemini_auth() -> bool:
    return _has_env("GEMINI_API_KEY") or _has_env("GOOGLE_GENERATIVE_AI_API_KEY")


def _fail_loud_for_openai(*, model: str) -> None:
    hints = ("CODEX_AUTH_JSON", "OPENAI_API_KEY")
    env_list = ", ".join(hints)
    msg = (
        f"OpenAI model {model!r} selected but no credential is configured. "
        f"Set {env_list} (subscription via `mergecraft auth codex`, or an API key secret) "
        "or choose a different model."
    )
    raise ValueError(msg)


def _fail_loud_for_google(*, model: str) -> None:
    hints = ("GEMINI_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY")
    env_list = ", ".join(hints)
    msg = (
        f"Google model {model!r} selected but no credential is configured. "
        f"Set {env_list} (via `mergecraft auth gemini` or a GitHub Actions secret) "
        "or choose a different model."
    )
    raise ValueError(msg)


def _resolve_slug(slug: str) -> str | None:
    alias = resolve_display_alias(slug)
    if alias and alias.routing == "bedrock":
        bedrock_id = os.environ.get(BEDROCK_MODEL_ID_ENV, "").strip()
        if not bedrock_id:
            msg = f"{BEDROCK_MODEL_ID_ENV} env var is required when the model is set to {slug!r}."
            raise ValueError(msg)
        return bedrock_id
    if alias and alias.routing == "vertex":
        vertex_id = os.environ.get(VERTEX_MODEL_ID_ENV, "").strip()
        if not vertex_id:
            msg = f"{VERTEX_MODEL_ID_ENV} env var is required when the model is set to {slug!r}."
            raise ValueError(msg)
        return vertex_id
    return resolve_cli_model(slug)


def resolve_model(*, slug: str | None = None) -> str | None:
    """Resolve the effective model string for this run."""
    env_model = os.environ.get("MERGECRAFT_MODEL", "").strip()
    if env_model:
        return _resolve_slug(env_model) or env_model

    cleaned = (slug or "").strip()
    if cleaned:
        resolved = _resolve_slug(cleaned)
        if resolved:
            return resolved
        if "/" in cleaned:
            logger.info(
                '» "{}" is not a curated alias — passing through as a raw model specifier',
                cleaned,
            )
            return cleaned
        logger.warning('» unknown model slug "{}" — agent will auto-select', cleaned)
    return None


def resolve_runtime_agent(*, model: str | None = None) -> Agent:
    """Pick claude vs opencode based on model + available credentials."""
    env_agent = os.environ.get("MERGECRAFT_AGENT", "").strip()
    if env_agent:
        if env_agent in agents:
            return resolve_agent(env_agent)
        logger.warning(
            '» unknown MERGECRAFT_AGENT="{}" — falling through to auto-select', env_agent
        )

    if model and _has_bedrock_auth() and os.environ.get(BEDROCK_MODEL_ID_ENV, "").strip() == model:
        return agents["claude"] if is_bedrock_anthropic_id(model) else agents["opencode"]

    if model and _has_vertex_auth() and os.environ.get(VERTEX_MODEL_ID_ENV, "").strip() == model:
        return agents["claude"] if is_vertex_anthropic_id(model) else agents["opencode"]

    if model:
        try:
            provider = get_model_provider(model)
        except ValueError:
            provider = None

        if provider == "openai":
            if _has_codex_subscription_auth() or _has_openai_api_key_auth():
                return agents["codex"]
            _fail_loud_for_openai(model=model)

        if provider == "google":
            if _has_gemini_auth():
                return agents["gemini"]
            _fail_loud_for_google(model=model)

        if provider == "anthropic" and _has_claude_code_auth():
            return agents["claude"]

    return agents["opencode"]


__all__ = ["resolve_model", "resolve_runtime_agent"]
