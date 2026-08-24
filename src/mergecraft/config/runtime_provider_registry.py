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

    msg = (
        f"configuration error: provider {provider!r} is not registered — "
        "add it with `mergecraft provider add`"
    )
    raise ValueError(msg)


__all__ = [
    "SEED_PROVIDER_URLS",
    "has_registry_credentials",
    "indexed_api_key_for_entry",
    "indexed_credential_for_entry",
    "indexed_env_key",
    "infer_harness_for_slug",
    "lookup_registry_entry",
    "registry_harness_for_provider",
    "resolve_registry_gateway_endpoint",
    "warn_legacy_nous_api_key_once",
]
