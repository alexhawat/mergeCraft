"""Known OpenAI-compatible gateways (Nous Portal, Tencent TokenHub).

These providers are reached through the opencode harness via
``@ai-sdk/openai-compatible``. Callers may still set
``MERGECRAFT_CUSTOM_PROVIDER_BASE_URL`` + ``MERGECRAFT_CUSTOM_PROVIDER_API_KEY``
to override any preset; when those are absent, model prefixes ``nous/`` and
``tokenhub/`` resolve from ``NOUS_API_KEY`` / ``TOKENHUB_API_KEY``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

NOUS_API_KEY_ENV = "NOUS_API_KEY"
NOUS_BASE_URL_ENV = "NOUS_BASE_URL"
DEFAULT_NOUS_BASE_URL = "https://inference-api.nousresearch.com/v1"

TOKENHUB_API_KEY_ENV = "TOKENHUB_API_KEY"
TOKENHUB_BASE_URL_ENV = "TOKENHUB_BASE_URL"
DEFAULT_TOKENHUB_BASE_URL = "https://tokenhub-intl.tencentcloudmaas.com/v1"

CUSTOM_PROVIDER_BASE_URL_ENV = "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL"
CUSTOM_PROVIDER_API_KEY_ENV = "MERGECRAFT_CUSTOM_PROVIDER_API_KEY"


@dataclass(frozen=True, slots=True)
class GatewayPreset:
    """One named OpenAI-compatible inference gateway."""

    provider_id: str
    api_key_env: str
    base_url_env: str
    default_base_url: str


GATEWAY_PRESETS: dict[str, GatewayPreset] = {
    "nous": GatewayPreset(
        provider_id="nous",
        api_key_env=NOUS_API_KEY_ENV,
        base_url_env=NOUS_BASE_URL_ENV,
        default_base_url=DEFAULT_NOUS_BASE_URL,
    ),
    "tokenhub": GatewayPreset(
        provider_id="tokenhub",
        api_key_env=TOKENHUB_API_KEY_ENV,
        base_url_env=TOKENHUB_BASE_URL_ENV,
        default_base_url=DEFAULT_TOKENHUB_BASE_URL,
    ),
}


def _has_env(name: str) -> bool:
    val = os.environ.get(name)
    return isinstance(val, str) and bool(val.strip())


def has_custom_provider_env() -> bool:
    """Return whether both generic custom-provider env vars are set."""
    return _has_env(CUSTOM_PROVIDER_BASE_URL_ENV) and _has_env(CUSTOM_PROVIDER_API_KEY_ENV)


def has_gateway_credentials(provider_id: str) -> bool:
    """Return whether ``provider_id`` can authenticate from the environment.

    For ``nous``, ``MERGECRAFT_CUSTOM_PROVIDER_API_KEY`` is honoured as a
    back-compat alias even when ``MERGECRAFT_CUSTOM_PROVIDER_BASE_URL`` is
    unset — the opencode harness contract re-passes ``NOUS_API_KEY`` as
    ``MERGECRAFT_CUSTOM_PROVIDER_API_KEY`` on the Nous step, so a workflow
    that wires the alias alone should still resolve credentials (D4).
    """
    if has_custom_provider_env():
        return True
    preset = GATEWAY_PRESETS.get(provider_id.lower())
    if preset is None:
        return False
    if _has_env(preset.api_key_env):
        return True
    return bool(provider_id.lower() == "nous" and _has_env(CUSTOM_PROVIDER_API_KEY_ENV))


def resolve_gateway_endpoint(model: str | None) -> tuple[str, str, str] | None:
    """Resolve ``(provider_id, base_url, api_key)`` for an OpenAI-compatible model.

    Preference order:

    1. Explicit ``MERGECRAFT_CUSTOM_PROVIDER_*`` pair (any ``provider/model`` slug)
    2. Named preset matching the model prefix (``nous/…``, ``tokenhub/…``)

    Returns ``None`` when credentials or a usable model prefix are missing.
    """
    if not model:
        return None
    slash = model.find("/")
    if slash <= 0:
        return None
    provider_id = model[:slash].lower()
    model_id = model[slash + 1 :]
    if not model_id:
        return None

    custom_base = os.environ.get(CUSTOM_PROVIDER_BASE_URL_ENV, "").strip()
    custom_key = os.environ.get(CUSTOM_PROVIDER_API_KEY_ENV, "").strip()
    if custom_base and custom_key:
        return provider_id, custom_base, custom_key

    preset = GATEWAY_PRESETS.get(provider_id)
    if preset is None:
        return None
    api_key = os.environ.get(preset.api_key_env, "").strip()
    if not api_key:
        return None
    base_url = os.environ.get(preset.base_url_env, "").strip() or preset.default_base_url
    return provider_id, base_url, api_key


__all__ = [
    "CUSTOM_PROVIDER_API_KEY_ENV",
    "CUSTOM_PROVIDER_BASE_URL_ENV",
    "DEFAULT_NOUS_BASE_URL",
    "DEFAULT_TOKENHUB_BASE_URL",
    "GATEWAY_PRESETS",
    "NOUS_API_KEY_ENV",
    "NOUS_BASE_URL_ENV",
    "TOKENHUB_API_KEY_ENV",
    "TOKENHUB_BASE_URL_ENV",
    "GatewayPreset",
    "has_custom_provider_env",
    "has_gateway_credentials",
    "resolve_gateway_endpoint",
]
