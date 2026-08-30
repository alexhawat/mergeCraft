"""Runtime provider-registry lookups for agent resolution (#481 / BE)."""

from __future__ import annotations

import os
import warnings
from typing import TYPE_CHECKING

from mergecraft.config.provider_registry import BUILTIN_HARNESS_DEFAULTS

if TYPE_CHECKING:
    from mergecraft.config.settings import ProviderRegistryEntry, RepoSettings

_LEGACY_NOUS_API_KEY = "NOUS_API_KEY"
_LEGACY_NOUS_WARNED = False

_AUTH_KIND_API_KEY = "api_key"
_AUTH_KIND_OAUTH = "oauth"
_AUTH_KIND_DEVICE_CODE = "device_code"
_AUTH_KIND_CLOUD_CHAIN = "cloud_chain"

_AUTH_KIND_PRIMARY_SUFFIX: dict[str, str] = {
    _AUTH_KIND_API_KEY: "API_KEY",
    _AUTH_KIND_OAUTH: "CLAUDE_CODE_OAUTH_TOKEN",
    _AUTH_KIND_DEVICE_CODE: "CODEX_AUTH_JSON",
}

_BEDROCK_CLOUD_SUFFIXES: tuple[str, ...] = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)

_VERTEX_CLOUD_SUFFIXES: tuple[str, ...] = ("GOOGLE_APPLICATION_CREDENTIALS",)

_BUILTIN_LABEL_TO_HARNESS_API_KEY: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GEMINI_API_KEY",
    "cursor": "CURSOR_API_KEY",
}

# Seed-only default URLs for ``provider seed`` — not used at runtime (BE / D4).
SEED_PROVIDER_URLS: dict[str, str] = {
    "nous": "https://inference-api.nousresearch.com/v1",
    "tokenhub": "https://tokenhub-intl.tencentcloudmaas.com/v1",
    "minimax": "https://api.minimax.io/v1",
}


def _read_env_value(key: str) -> str | None:
    value = os.environ.get(key, "").strip()
    return value or None


def indexed_env_key(env_index: int, suffix: str) -> str:
    """Return ``LLM_PROVIDER_<N>_<SUFFIX>``."""
    return f"LLM_PROVIDER_{env_index}_{suffix}"


def lookup_registry_entry(
    settings: RepoSettings | None,
    label: str,
) -> ProviderRegistryEntry | None:
    """Return the registry row for *label*, or ``None`` when absent."""
    if settings is None:
        return None
    lowered = label.strip().lower()
    for entry in settings.providers:
        if entry.label.strip().lower() == lowered:
            return entry
    return None


def lookup_registry_entry_by_env_index(
    settings: RepoSettings | None,
    env_index: int,
) -> ProviderRegistryEntry | None:
    """Return the registry row for *env_index*, or ``None`` when absent."""
    if settings is None:
        return None
    for entry in settings.providers:
        if entry.env_index == env_index:
            return entry
    return None


def _provider_id_for_env_index(env_index: int) -> str:
    from mergecraft.config.settings_snapshot import repo_settings_for_gateway_resolvers

    settings = repo_settings_for_gateway_resolvers()
    entry = lookup_registry_entry_by_env_index(settings, env_index)
    if entry is not None:
        return entry.label.strip().lower()
    return f"provider_{env_index}"


def registry_harness_for_provider(
    settings: RepoSettings | None,
    provider: str,
) -> str | None:
    """Return the configured harness for *provider* when registered."""
    entry = lookup_registry_entry(settings, provider)
    if entry is None:
        return None
    return entry.harness


def indexed_api_key_for_entry(entry: ProviderRegistryEntry) -> str | None:
    """Read ``LLM_PROVIDER_<envIndex>_API_KEY`` for one registry row."""
    return _read_env_value(indexed_env_key(entry.env_index, "API_KEY"))


def _credential_suffixes_for_entry(entry: ProviderRegistryEntry) -> tuple[str, ...]:
    auth_kind = (entry.auth_kind or _AUTH_KIND_API_KEY).strip().lower()
    if auth_kind == _AUTH_KIND_CLOUD_CHAIN:
        label = entry.label.strip().lower()
        if label == "bedrock":
            return _BEDROCK_CLOUD_SUFFIXES
        if label == "vertex":
            return _VERTEX_CLOUD_SUFFIXES
        return _BEDROCK_CLOUD_SUFFIXES
    suffix = _AUTH_KIND_PRIMARY_SUFFIX.get(auth_kind, "API_KEY")
    if suffix != "API_KEY":
        return ("API_KEY", suffix)
    return (suffix,)


def credential_env_keys_for_entry(entry: ProviderRegistryEntry) -> tuple[str, ...]:
    """Return the indexed env keys that can satisfy *entry*, in preference order.

    The keys are **alternatives**, not requirements: an ``oauth`` entry is
    satisfied by ``LLM_PROVIDER_<N>_CLAUDE_CODE_OAUTH_TOKEN`` and a
    ``device_code`` entry by ``LLM_PROVIDER_<N>_CODEX_AUTH_JSON``, neither of
    which is an API key. Callers that check for a *missing* credential must
    treat the whole tuple as one OR, the way ``indexed_credential_for_entry``
    does when it reads them.
    """
    return tuple(
        indexed_env_key(entry.env_index, suffix) for suffix in _credential_suffixes_for_entry(entry)
    )


def indexed_credential_for_entry(entry: ProviderRegistryEntry) -> str | None:
    """Return the first indexed credential value present for *entry*."""
    for suffix in _credential_suffixes_for_entry(entry):
        value = _read_env_value(indexed_env_key(entry.env_index, suffix))
        if value:
            return value
    workflow_key = f"MERGECRAFT_CUSTOM_PROVIDER_API_KEY_{entry.env_index}"
    return _read_env_value(workflow_key)


def _indexed_credential_for_entry(entry: ProviderRegistryEntry) -> str | None:
    """Backward-compatible alias for :func:`indexed_credential_for_entry`."""
    return indexed_credential_for_entry(entry)


def has_registry_credentials(
    settings: RepoSettings | None,
    provider: str,
) -> bool:
    """Return whether indexed registry credentials exist for *provider*."""
    entry = lookup_registry_entry(settings, provider)
    if entry is None:
        return False
    if _indexed_credential_for_entry(entry):
        return True
    if provider == "nous":
        return _legacy_nous_api_key_present()
    return False


def _legacy_nous_api_key_present() -> bool:
    return bool(_read_env_value(_LEGACY_NOUS_API_KEY))


def warn_legacy_nous_api_key_once() -> None:
    """Emit one DeprecationWarning per process when ``NOUS_API_KEY`` is used (D7)."""
    global _LEGACY_NOUS_WARNED
    if _LEGACY_NOUS_WARNED:
        return
    _LEGACY_NOUS_WARNED = True
    warnings.warn(
        "NOUS_API_KEY is deprecated; use `mergecraft provider auth nous` to write "
        "LLM_PROVIDER_<N>_API_KEY instead.",
        DeprecationWarning,
        stacklevel=3,
    )


def legacy_opencode_harness_for_provider(provider: str) -> str | None:
    """Return ``opencode`` when D7 legacy env credentials exist for *provider*."""
    if provider == "nous" and _legacy_nous_api_key_present():
        warn_legacy_nous_api_key_once()
        return "opencode"
    from mergecraft.agents.openai_compatible_gateways import _legacy_gateway_preset_credentials

    if _legacy_gateway_preset_credentials(provider):
        return "opencode"
    return None


def legacy_opencode_harness_for_unregistered_provider(
    settings: RepoSettings | None,
    provider: str,
) -> str | None:
    """Return ``opencode`` when D7 legacy credentials exist without a registry row."""
    if lookup_registry_entry(settings, provider) is not None:
        return None
    return legacy_opencode_harness_for_provider(provider)


def resolve_legacy_nous_gateway_endpoint(
    provider_id: str,
    *,
    settings: RepoSettings | None = None,
) -> tuple[str, str, str] | None:
    """Resolve legacy ``NOUS_API_KEY`` when no registry row exists (D7)."""
    if provider_id != "nous":
        return None
    if lookup_registry_entry(settings, provider_id) is not None:
        return None
    api_key = _read_env_value(_LEGACY_NOUS_API_KEY)
    if not api_key:
        return None
    base_url = SEED_PROVIDER_URLS.get("nous")
    if not base_url:
        return None
    warn_legacy_nous_api_key_once()
    return provider_id, base_url, api_key


def resolve_registry_gateway_endpoint(
    model: str,
    *,
    settings: RepoSettings | None = None,
) -> tuple[str, str, str] | None:
    """Resolve ``(provider_id, base_url, api_key)`` from the operator registry."""
    slash = model.find("/")
    if slash <= 0:
        return None
    provider_id = model[:slash].lower()
    entry = lookup_registry_entry(settings, provider_id)
    if entry is None or not entry.url:
        return None
    api_key = indexed_api_key_for_entry(entry)
    if not api_key:
        api_key = _indexed_credential_for_entry(entry)
    if not api_key and provider_id == "nous":
        api_key = _read_env_value(_LEGACY_NOUS_API_KEY)
        if api_key:
            warn_legacy_nous_api_key_once()
    if not api_key:
        return None
    return provider_id, entry.url, api_key


def _harness_env_name_for_suffix(label: str, suffix: str) -> str | None:
    """Map one indexed credential suffix to the harness env var native CLIs consume."""
    if suffix == "API_KEY":
        return _BUILTIN_LABEL_TO_HARNESS_API_KEY.get(label.strip().lower())
    if suffix in {
        "CODEX_AUTH_JSON",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "VERTEX_SERVICE_ACCOUNT_JSON",
        "GOOGLE_CLOUD_PROJECT",
        "CLOUD_ML_PROJECT_ID",
        "VERTEX_LOCATION",
    }:
        return suffix
    return None


def _read_indexed_credential_value(entry: ProviderRegistryEntry, suffix: str) -> str | None:
    value = _read_env_value(indexed_env_key(entry.env_index, suffix))
    if value:
        return value
    if suffix == "API_KEY":
        workflow_key = f"MERGECRAFT_CUSTOM_PROVIDER_API_KEY_{entry.env_index}"
        return _read_env_value(workflow_key)
    return None


def harness_env_for_active_provider(
    model: str | None,
    agent_id: str,
) -> dict[str, str]:
    """Map indexed registry credentials into legacy harness env names for *agent_id*.

    Only the active model's provider row is mapped — indexed secrets are copied
    into the env vars Codex / Claude / Gemini / Cursor subprocesses read
    (``OPENAI_API_KEY``, ``CODEX_AUTH_JSON``, ``CLAUDE_CODE_OAUTH_TOKEN``, etc.).
    """
    if not model:
        return {}
    from mergecraft.models import get_model_provider

    try:
        provider = get_model_provider(model)
    except ValueError:
        return {}

    from mergecraft.config.settings_snapshot import repo_settings_for_gateway_resolvers

    settings = repo_settings_for_gateway_resolvers()
    entry = lookup_registry_entry(settings, provider)
    if entry is None or entry.harness != agent_id:
        return {}

    mapped: dict[str, str] = {}
    for suffix in _credential_suffixes_for_entry(entry):
        value = _read_indexed_credential_value(entry, suffix)
        if not value:
            continue
        harness_key = _harness_env_name_for_suffix(entry.label, suffix)
        if harness_key is not None:
            mapped[harness_key] = value
    return mapped


def infer_harness_for_slug(
    slug: str,
    *,
    settings: RepoSettings | None = None,
) -> str:
    """Resolve harness for *slug* from registry rows or built-in defaults.

    Raises:
        ValueError: When the provider is unknown / unregistered.
    """
    from mergecraft.models import get_model_provider

    provider = get_model_provider(slug)
    registry_harness = registry_harness_for_provider(settings, provider)
    if registry_harness is not None:
        return registry_harness

    builtin = BUILTIN_HARNESS_DEFAULTS.get(provider)
    if builtin is not None:
        return builtin

    legacy_harness = legacy_opencode_harness_for_unregistered_provider(settings, provider)
    if legacy_harness is not None:
        return legacy_harness

    msg = (
        f"configuration error: provider {provider!r} is not registered — "
        "add it with `mergecraft provider add`"
    )
    raise ValueError(msg)


__all__ = [
    "SEED_PROVIDER_URLS",
    "credential_env_keys_for_entry",
    "harness_env_for_active_provider",
    "has_registry_credentials",
    "indexed_api_key_for_entry",
    "indexed_credential_for_entry",
    "indexed_env_key",
    "infer_harness_for_slug",
    "legacy_opencode_harness_for_provider",
    "legacy_opencode_harness_for_unregistered_provider",
    "lookup_registry_entry",
    "lookup_registry_entry_by_env_index",
    "registry_harness_for_provider",
    "resolve_legacy_nous_gateway_endpoint",
    "resolve_registry_gateway_endpoint",
    "warn_legacy_nous_api_key_once",
]
