"""Resolve model slug + agent implementation for a run."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from mergecraft.agents import agents, resolve_agent
from mergecraft.models import (
    _MAX_FALLBACK_DEPTH,
    BEDROCK_MODEL_ID_ENV,
    MODEL_ALIASES,
    VERTEX_MODEL_ID_ENV,
    ModelAlias,
    get_model_provider,
    is_bedrock_anthropic_id,
    is_vertex_anthropic_id,
    resolve_cli_model,
    resolve_display_alias,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mergecraft.agents.shared import Agent, AgentResult
    from mergecraft.config.settings import RepoSettings


def _has_env(name: str) -> bool:
    val = os.environ.get(name)
    return isinstance(val, str) and bool(val.strip())


def _has_claude_code_auth() -> bool:
    return _has_env("CLAUDE_CODE_OAUTH_TOKEN") or _has_env("ANTHROPIC_API_KEY")


def _has_bedrock_auth() -> bool:
    return _has_env("AWS_BEARER_TOKEN_BEDROCK") or (
        _has_env("AWS_ACCESS_KEY_ID") and _has_env("AWS_SECRET_ACCESS_KEY")
    )


def _has_vertex_auth() -> bool:
    return _has_env("GOOGLE_APPLICATION_CREDENTIALS") or _has_env("VERTEX_SERVICE_ACCOUNT_JSON")


def _has_codex_subscription_auth() -> bool:
    raw = os.environ.get("CODEX_AUTH_JSON", "").strip()
    if not raw:
        return False
    from mergecraft.agents.codex import _codex_subscription_auth_usable

    return _codex_subscription_auth_usable(raw)


def _has_openai_api_key_auth() -> bool:
    return _has_env("OPENAI_API_KEY")


def _has_gemini_auth() -> bool:
    return _has_env("GEMINI_API_KEY") or _has_env("GOOGLE_GENERATIVE_AI_API_KEY")


def _has_cursor_auth() -> bool:
    return _has_env("CURSOR_API_KEY")


def has_credentials_for_slug(slug: str) -> bool:
    """Return whether the current environment has credentials for ``slug``."""
    try:
        provider = get_model_provider(slug)
    except ValueError:
        return False

    if provider == "anthropic":
        return _has_claude_code_auth()
    if provider == "openai":
        return _has_codex_subscription_auth() or _has_openai_api_key_auth()
    if provider == "google":
        return _has_gemini_auth()
    if provider == "cursor":
        return _has_cursor_auth()
    if provider == "bedrock":
        return _has_bedrock_auth() and bool(os.environ.get(BEDROCK_MODEL_ID_ENV, "").strip())
    if provider == "vertex":
        return _has_vertex_auth() and bool(os.environ.get(VERTEX_MODEL_ID_ENV, "").strip())
    return False


def _ctx_tmpdir_fallback() -> str:
    return os.environ.get("MERGECRAFT_TEMP_DIR") or "/tmp"


def _local_agent_binary(name: str) -> Path:
    return Path(_ctx_tmpdir_fallback()) / "node_modules" / ".bin" / name


def _agent_binary_available(slug: str) -> bool:
    try:
        provider = get_model_provider(slug)
    except ValueError:
        return False

    binary_by_provider = {
        "anthropic": "claude",
        "openai": "codex",
        "google": "gemini",
        "cursor": "cursor",
    }
    binary = binary_by_provider.get(provider)
    if binary is None:
        return True
    if shutil.which(binary):
        return True
    return _local_agent_binary(binary).exists()


def is_runnable_model_slug(slug: str) -> bool:
    """Return whether ``slug`` has credentials and an agent CLI available."""
    if not has_credentials_for_slug(slug):
        return False
    return _agent_binary_available(slug)


def _configured_model_slugs(settings: RepoSettings) -> list[str]:
    if settings.models:
        return list(settings.models)
    if settings.model:
        return [settings.model]
    return []


def effective_model_slugs(settings: RepoSettings) -> list[str]:
    """Config order with ``MERGECRAFT_MODEL`` promoted to the front when set."""
    base = _configured_model_slugs(settings)
    env_model = os.environ.get("MERGECRAFT_MODEL", "").strip()
    if not env_model:
        return base
    rest = [slug for slug in base if slug != env_model]
    return [env_model, *rest]


def _alias_for_slug(slug: str) -> ModelAlias | None:
    return next(
        (alias for alias in MODEL_ALIASES if alias.slug == slug or alias.resolve == slug), None
    )


def _catalog_fallback_tail(slug: str) -> list[str]:
    tail: list[str] = []
    current = slug
    visited: set[str] = set()
    for _ in range(_MAX_FALLBACK_DEPTH):
        alias = _alias_for_slug(current)
        if alias is None or not alias.fallback:
            break
        nxt = alias.fallback
        if nxt in visited:
            break
        visited.add(nxt)
        tail.append(nxt)
        current = nxt
    return tail


def _expand_slug_with_fallbacks(slug: str, settings: RepoSettings) -> list[str]:
    entries = [slug]
    configured = (settings.model_fallbacks or {}).get(slug, [])
    for fallback in configured:
        if fallback not in entries:
            entries.append(fallback)
    for fallback in _catalog_fallback_tail(slug):
        if fallback not in entries:
            entries.append(fallback)
    return entries


def effective_model_chain(settings: RepoSettings) -> list[str]:
    """Ordered chain: config ``models``/``modelFallbacks``, env override, catalog ``fallback:``."""
    configured = _configured_model_slugs(settings)
    explicit_chain = len(configured) > 1 or bool(settings.model_fallbacks)

    chain: list[str] = []
    for slug in configured:
        if explicit_chain:
            entries = [slug]
            for fallback in (settings.model_fallbacks or {}).get(slug, []):
                if fallback not in entries:
                    entries.append(fallback)
        else:
            entries = _expand_slug_with_fallbacks(slug, settings)
        for entry in entries:
            if entry not in chain:
                chain.append(entry)

    env_model = os.environ.get("MERGECRAFT_MODEL", "").strip()
    if env_model:
        if explicit_chain:
            expanded = [env_model]
            for fallback in (settings.model_fallbacks or {}).get(env_model, []):
                if fallback not in expanded:
                    expanded.append(fallback)
        else:
            expanded = _expand_slug_with_fallbacks(env_model, settings)
        chain = expanded + [entry for entry in chain if entry not in expanded]

    return chain[:_MAX_FALLBACK_DEPTH]


def select_runnable_model_slug(*, settings: RepoSettings) -> str:
    """Pick the first chain entry with credentials and an available agent binary."""
    chain = effective_model_chain(settings)
    if not chain:
        msg = "no model chain configured — set models: or model: in .mergecraft/config.yaml"
        raise RuntimeError(msg)

    skipped: list[str] = []
    for slug in chain:
        if not has_credentials_for_slug(slug):
            skipped.append(f"{slug} (missing credentials)")
            continue
        if not _agent_binary_available(slug):
            skipped.append(f"{slug} (agent binary missing)")
            continue
        if skipped:
            logger.warning("» model chain skipped backups: {}", ", ".join(skipped))
        logger.info("» model chain selected slug={}", slug)
        return slug

    if skipped:
        logger.warning("» model chain skipped backups: {}", ", ".join(skipped))
    msg = "no runnable model slug in chain — configure credentials for at least one entry"
    raise RuntimeError(msg)


def _is_retryable_failure(result: AgentResult) -> bool:
    metadata = result.metadata or {}
    retryable = metadata.get("retryable")
    return retryable is True


async def run_with_model_chain(
    *,
    settings: RepoSettings,
    run_once: Callable[[str], Awaitable[AgentResult]],
    max_attempts: int = _MAX_FALLBACK_DEPTH,
) -> tuple[str, AgentResult]:
    """Walk the model chain, skipping unrunnable entries and advancing on retryable failures."""
    chain = effective_model_chain(settings)
    if not chain:
        msg = "no model chain configured"
        raise RuntimeError(msg)

    runnable: list[str] = []
    skipped: list[str] = []
    for slug in chain:
        if not has_credentials_for_slug(slug):
            skipped.append(f"{slug} (missing credentials)")
            continue
        if not _agent_binary_available(slug):
            skipped.append(f"{slug} (agent binary missing)")
            continue
        runnable.append(slug)

    if skipped:
        logger.warning("» model chain skipped backups: {}", ", ".join(skipped))

    if not runnable:
        msg = "no runnable model slug in chain"
        raise RuntimeError(msg)

    chain_index = 0
    attempts = 0

    while attempts < max_attempts:
        slug = runnable[chain_index]
        attempts += 1
        logger.info("» model chain attempt {}/{} slug={}", attempts, max_attempts, slug)
        result = await run_once(slug)

        if result.success:
            logger.info("» model chain succeeded slug={}", slug)
            return slug, result

        if not _is_retryable_failure(result):
            logger.warning(
                "» model chain slug={} failed (non-retryable): {}",
                slug,
                result.error or "unknown error",
            )
            return slug, result

        if chain_index < len(runnable) - 1:
            nxt = runnable[chain_index + 1]
            logger.warning(
                "» model chain slug={} failed (retryable): {} — advancing to {}",
                slug,
                result.error or "unknown error",
                nxt,
            )
            chain_index += 1
            continue

        logger.warning(
            "» model chain slug={} failed (retryable): {} — retrying ({}/{})",
            slug,
            result.error or "unknown error",
            attempts,
            max_attempts,
        )

    msg = f"model chain exhausted after {max_attempts} attempts (cap reached)"
    raise RuntimeError(msg) from None


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


def _fail_loud_for_cursor(*, model: str) -> None:
    hints = ("CURSOR_API_KEY",)
    env_list = ", ".join(hints)
    msg = (
        f"Cursor model {model!r} selected but no credential is configured. "
        f"Set {env_list} (via `mergecraft auth cursor` or a GitHub Actions secret) "
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


def resolve_model(*, slug: str | None = None, respect_env_override: bool = True) -> str | None:
    """Resolve the effective model string for this run."""
    if respect_env_override:
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

        if provider == "cursor":
            if _has_cursor_auth():
                return agents["cursor"]
            _fail_loud_for_cursor(model=model)

        if provider == "anthropic" and _has_claude_code_auth():
            return agents["claude"]

    return agents["opencode"]


__all__ = [
    "effective_model_chain",
    "effective_model_slugs",
    "has_credentials_for_slug",
    "is_runnable_model_slug",
    "resolve_model",
    "resolve_runtime_agent",
    "run_with_model_chain",
    "select_runnable_model_slug",
]
