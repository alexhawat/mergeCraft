"""Resolve model aliases, executable availability, and the runtime agent harness.

Module: mergecraft.agents.resolution.runtime
Depends: mergecraft.{agents,config,enterprise,errors,models}, loguru

Exports:
    Functions:
        agent_binary_available — Check whether a model's harness is available.
        resolve_harness — Apply registry and harness selection policy to a model.
        resolve_model — Resolve a model slug for the selected harness.
        resolve_runtime_agent — Select the agent for a model and current credentials.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from mergecraft.agents import agents, resolve_agent
from mergecraft.agents.resolution import credentials
from mergecraft.config.env import AgentRuntimeEnv
from mergecraft.errors import ModelFallbackPolicyError
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
    from mergecraft.config.settings import RepoSettings


def _ctx_tmpdir_fallback() -> str:
    return os.environ.get("MERGECRAFT_TEMP_DIR") or "/tmp"


def local_agent_binary(name: str) -> Path:
    """Return the expected path to a locally installed harness binary."""
    return Path(_ctx_tmpdir_fallback()) / "node_modules" / ".bin" / name


def agent_binary_available(slug: str) -> bool:
    """Return whether the slug has an available harness binary."""
    try:
        provider = get_model_provider(slug)
    except ValueError:
        return False

    from mergecraft.config.runtime_provider_registry import lookup_registry_entry
    from mergecraft.config.settings import load_repo_settings

    settings = load_repo_settings(root=Path.cwd(), load_learnings_files=False)
    entry = lookup_registry_entry(settings, provider)
    if entry is not None and entry.harness == "opencode":
        return True

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
    return local_agent_binary(binary).exists()


def agent_provider_for_slug(slug: str) -> str:
    """Return the provider slug (``anthropic`` / ``openai`` / ...) for ``slug``."""
    try:
        return get_model_provider(slug)
    except ValueError:
        return "unknown"


def agent_mode_for_slug(slug: str, *, settings: RepoSettings | None = None) -> str:
    """Return the agent mode name (e.g. ``claude``) that would serve ``slug``."""
    from mergecraft.config.runtime_provider_registry import infer_harness_for_slug
    from mergecraft.config.settings import load_repo_settings

    resolved_settings = settings or load_repo_settings(root=Path.cwd(), load_learnings_files=False)
    try:
        return infer_harness_for_slug(slug, settings=resolved_settings)
    except ValueError as exc:
        raise ModelFallbackPolicyError(str(exc)) from exc


NATIVE_HARNESS_PROVIDERS: dict[str, frozenset[str]] = {
    "codex": frozenset({"openai"}),
    "claude": frozenset({"anthropic"}),
    "gemini": frozenset({"google"}),
    "cursor": frozenset({"cursor"}),
}

# OpenCode natively serves OpenAI-compatible slugs for these built-in prefixes when
# explicitly overridden to ``harness: opencode`` in the operator registry.
OPENCODE_NATIVE_PROVIDERS = frozenset({"openai", "anthropic"})
KNOWN_CATALOG_PROVIDERS = frozenset(
    {
        "anthropic",
        "openai",
        "google",
        "cursor",
        "bedrock",
        "vertex",
        "xai",
        "deepseek",
        "moonshotai",
        "opencode",
        "opencode-go",
        "openrouter",
    }
)


def harness_supports_provider(harness: str, provider: str) -> bool:
    """Return whether ``harness`` may run models from ``provider``."""
    if harness == "opencode":
        return provider in OPENCODE_NATIVE_PROVIDERS
    native = NATIVE_HARNESS_PROVIDERS.get(harness)
    return native is not None and provider in native


def _raise_if_curated_requires_opencode(slug: str, harness: str) -> None:
    from mergecraft.agents.curated_model_catalog import require_opencode_harness_for_model

    try:
        require_opencode_harness_for_model(slug, harness)
    except ValueError as exc:
        raise ModelFallbackPolicyError(str(exc)) from exc


def _finalize_resolved_harness(slug: str, harness: str) -> str:
    """Apply curated-model harness policy before returning a resolved harness."""
    _raise_if_curated_requires_opencode(slug, harness)
    return harness


def resolve_harness(settings: RepoSettings, slug: str) -> str:
    """Resolve the agent harness for ``slug`` under ``settings`` (HA3 / D11).

    Registry rows win over built-in inference. Unsupported combinations raise
    :class:`ModelFallbackPolicyError` so ``main._classify_error_outcome`` maps
    them to ``configuration_error``.
    """
    from mergecraft.config.runtime_provider_registry import registry_harness_for_provider

    provider = agent_provider_for_slug(slug)

    if settings.harness is not None and settings.harness != "opencode":
        _raise_if_curated_requires_opencode(slug, settings.harness)

    if settings.harness is None:
        registry_harness = registry_harness_for_provider(settings, provider)
        if registry_harness is not None:
            if registry_harness == "opencode" or harness_supports_provider(
                registry_harness, provider
            ):
                return _finalize_resolved_harness(slug, registry_harness)
            _raise_if_curated_requires_opencode(slug, registry_harness)
            msg = (
                f"configuration error: harness {registry_harness!r} is incompatible with "
                f"model {slug!r} (provider {provider!r})"
            )
            raise ModelFallbackPolicyError(msg)
        return _finalize_resolved_harness(slug, agent_mode_for_slug(slug, settings=settings))

    harness = settings.harness
    if harness_supports_provider(harness, provider):
        return _finalize_resolved_harness(slug, harness)

    _raise_if_curated_requires_opencode(slug, harness)
    msg = (
        f"configuration error: harness {harness!r} is incompatible with "
        f"model {slug!r} (provider {provider!r})"
    )
    raise ModelFallbackPolicyError(msg)


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
    """Resolve the effective model string for this run.

    Precedence matches :class:`mergecraft.cli.config_precedence.ConfigLayer`:
    an explicit ``slug`` (the CLI layer) outranks ``MERGECRAFT_MODEL`` (the
    env layer). ``respect_env_override=False`` drops the env layer entirely
    for callers that have already applied their own precedence (the Action
    chain in :mod:`mergecraft.main` resolves a winning slug up front).

    An explicit slug is never discarded silently — when it is dropped in
    favour of the env override, or when it resolves to nothing, that is
    reported.
    """
    cleaned = (slug or "").strip()
    env_model = (AgentRuntimeEnv().model or "") if respect_env_override else ""

    if cleaned:
        _enforce_resolved_model_residency(cleaned)
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

    if env_model:
        _enforce_resolved_model_residency(env_model)
        return _resolve_slug(env_model) or env_model
    return None


def _enforce_resolved_model_residency(model_id: str) -> None:
    from mergecraft.enterprise.runtime import enforce_routed_model_residency

    enforce_routed_model_residency(model_id)


def resolve_runtime_agent(
    *,
    model: str | None = None,
    settings: RepoSettings | None = None,
) -> Agent:
    """Pick the runtime agent from model, credentials, and optional ``harness:``.

    ``MERGECRAFT_AGENT`` still wins when set. When ``settings.harness`` is
    set, the explicit harness is validated against the model (D11) and
    returned — so ``harness: opencode`` with an OpenAI slug runs OpenCode
    instead of Codex. When unset, today's provider/credential inference
    applies, including fail-loud for missing native-harness credentials.
    """
    env_agent = AgentRuntimeEnv().agent or ""
    if env_agent:
        if env_agent in agents:
            return resolve_agent(env_agent)
        logger.warning(
            '» unknown MERGECRAFT_AGENT="{}" — falling through to auto-select', env_agent
        )

    if settings is not None and settings.harness is not None:
        harness = resolve_harness(settings, model) if model else settings.harness
        return resolve_agent(harness)

    if (
        model
        and credentials.has_bedrock_auth()
        and os.environ.get(BEDROCK_MODEL_ID_ENV, "").strip() == model
    ):
        return agents["claude"] if is_bedrock_anthropic_id(model) else agents["opencode"]

    if (
        model
        and credentials.has_vertex_auth()
        and os.environ.get(VERTEX_MODEL_ID_ENV, "").strip() == model
    ):
        return agents["claude"] if is_vertex_anthropic_id(model) else agents["opencode"]

    if model:
        from mergecraft.config.runtime_provider_registry import (
            indexed_credential_for_entry,
            lookup_registry_entry,
        )
        from mergecraft.config.settings import load_repo_settings

        try:
            provider = get_model_provider(model)
        except ValueError:
            provider = None

        resolved_settings = settings or load_repo_settings(
            root=Path.cwd(), load_learnings_files=False
        )

        if provider == "openai":
            if credentials.has_codex_subscription_auth() or credentials.has_openai_api_key_auth():
                return agents["codex"]
            openai_entry = lookup_registry_entry(resolved_settings, provider)
            if openai_entry is not None:
                if indexed_credential_for_entry(openai_entry):
                    return resolve_agent(openai_entry.harness)
                msg = (
                    f"configuration error: provider {provider!r} is registered but missing "
                    f"credentials — run `mergecraft provider auth {provider}`"
                )
                raise ModelFallbackPolicyError(msg)
            _fail_loud_for_openai(model=model)

        if provider == "google":
            if credentials.has_gemini_auth():
                return agents["gemini"]
            google_entry = lookup_registry_entry(resolved_settings, provider)
            if google_entry is not None:
                if indexed_credential_for_entry(google_entry):
                    return resolve_agent(google_entry.harness)
                msg = (
                    f"configuration error: provider {provider!r} is registered but missing "
                    f"credentials — run `mergecraft provider auth {provider}`"
                )
                raise ModelFallbackPolicyError(msg)
            _fail_loud_for_google(model=model)

        if provider == "cursor":
            if credentials.has_cursor_auth():
                return agents["cursor"]
            cursor_entry = lookup_registry_entry(resolved_settings, provider)
            if cursor_entry is not None:
                if indexed_credential_for_entry(cursor_entry):
                    return resolve_agent(cursor_entry.harness)
                msg = (
                    f"configuration error: provider {provider!r} is registered but missing "
                    f"credentials — run `mergecraft provider auth {provider}`"
                )
                raise ModelFallbackPolicyError(msg)
            _fail_loud_for_cursor(model=model)

        if provider == "anthropic":
            if credentials.has_claude_code_auth():
                return agents["claude"]
            anthropic_entry = lookup_registry_entry(resolved_settings, provider)
            if anthropic_entry is not None:
                if indexed_credential_for_entry(anthropic_entry):
                    return resolve_agent(anthropic_entry.harness)
                msg = (
                    f"configuration error: provider {provider!r} is registered but missing "
                    f"credentials — run `mergecraft provider auth {provider}`"
                )
                raise ModelFallbackPolicyError(msg)
            msg = (
                f"configuration error: provider {provider!r} is not registered — "
                "add it with `mergecraft provider add`"
            )
            raise ModelFallbackPolicyError(msg)

        if provider in {"opencode", "opencode-go"}:
            if credentials.has_opencode_zen_auth():
                return agents["opencode"]
            zen_entry = lookup_registry_entry(resolved_settings, provider)
            if zen_entry is not None:
                if indexed_credential_for_entry(zen_entry):
                    return resolve_agent(zen_entry.harness)
                msg = (
                    f"configuration error: provider {provider!r} is registered but missing "
                    f"credentials — run `mergecraft provider auth {provider}`"
                )
                raise ModelFallbackPolicyError(msg)
            msg = (
                f"configuration error: OpenCode Zen credentials missing — set "
                f"OPENCODE_AUTH_JSON (mergecraft provider auth {provider}) or OPENCODE_API_KEY"
            )
            raise ModelFallbackPolicyError(msg)

        entry = lookup_registry_entry(resolved_settings, provider) if provider else None
        if entry is not None:
            if indexed_credential_for_entry(entry):
                return resolve_agent(entry.harness)
            from mergecraft.config.runtime_provider_registry import (
                legacy_opencode_harness_for_provider,
            )

            assert provider is not None
            legacy_harness = legacy_opencode_harness_for_provider(provider)
            if legacy_harness is not None:
                return resolve_agent(legacy_harness)
            msg = (
                f"configuration error: provider {provider!r} is registered but missing "
                f"credentials — run `mergecraft provider auth {provider}`"
            )
            raise ModelFallbackPolicyError(msg)

        if provider is not None:
            from mergecraft.config.runtime_provider_registry import (
                legacy_opencode_harness_for_unregistered_provider,
            )

            legacy_harness = legacy_opencode_harness_for_unregistered_provider(
                resolved_settings,
                provider,
            )
            if legacy_harness is not None:
                return resolve_agent(legacy_harness)

            msg = (
                f"configuration error: provider {provider!r} is not registered — "
                "add it with `mergecraft provider add`"
            )
            raise ModelFallbackPolicyError(msg)

    return agents["opencode"]


__all__ = [
    "KNOWN_CATALOG_PROVIDERS",
    "NATIVE_HARNESS_PROVIDERS",
    "OPENCODE_NATIVE_PROVIDERS",
    "agent_binary_available",
    "agent_mode_for_slug",
    "agent_provider_for_slug",
    "harness_supports_provider",
    "local_agent_binary",
    "resolve_harness",
    "resolve_model",
    "resolve_runtime_agent",
]
