"""OpenAI-compatible gateway helpers for the opencode harness.

Operators configure providers through the registry (``.mergecraft/config.yaml``
``providers:`` + indexed ``LLM_PROVIDER_<N>_API_KEY`` secrets). The singleton
``MERGECRAFT_CUSTOM_PROVIDER_{BASE_URL,API_KEY}`` pair and indexed
``MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}_<N>`` env vars remain as
generic OpenAI-compatible escape hatches for advanced deployments.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import urlparse

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.functional_serializers import PlainSerializer
from pydantic.functional_validators import BeforeValidator

if TYPE_CHECKING:
    from mergecraft.tracing.genai import ModelParams

CUSTOM_PROVIDER_BASE_URL_ENV = "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL"
CUSTOM_PROVIDER_API_KEY_ENV = "MERGECRAFT_CUSTOM_PROVIDER_API_KEY"
CUSTOM_PROVIDER_EXTRA_OPTIONS_ENV = "MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS"
PROVIDER_EXTRA_OPTIONS_ENV = "MERGECRAFT_PROVIDER_EXTRA_OPTIONS"

# Indexed multi-provider convention (W3 / issue #71). Both halves must be
# set per index; partial pairs are dropped. Discovery enumerates every
# matching env-var suffix and pairs by numeric N. Gaps are preserved
# (no renumbering).
INDEXED_CUSTOM_PROVIDER_BASE_URL_RE = re.compile(r"^MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_(\d+)$")
INDEXED_CUSTOM_PROVIDER_API_KEY_RE = re.compile(r"^MERGECRAFT_CUSTOM_PROVIDER_API_KEY_(\d+)$")
INDEXED_CUSTOM_PROVIDER_EXTRA_OPTIONS_FMT = "MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS_{n}"
# Provider-id derivation rule (operator locked): ``"provider_" + str(N)`` for
# indexed pairs; ``"default"`` for the singleton back-compat alias.
INDEXED_PROVIDER_ID_FMT = "provider_{n}"
SINGLETON_PROVIDER_ID = "default"

# Closed capability vocabulary (HA1 / D12). ``context_limit`` is a sibling
# field on ``ProviderConfig``, not a set member.
CAPABILITY_VALUES: frozenset[str] = frozenset(
    {
        "tool_calling",
        "streaming",
        "reasoning_controls",
        "structured_output",
        "custom_base_url",
        "openai_compatible",
        "native_opencode",
    }
)

_DEFAULT_GATEWAY_CAPABILITIES: frozenset[str] = frozenset(
    {"openai_compatible", "custom_base_url", "tool_calling", "streaming"}
)


def _coerce_capabilities(value: object) -> frozenset[str]:
    if isinstance(value, frozenset):
        items = value
    elif isinstance(value, (list, set, tuple)):
        items = frozenset(str(item) for item in value)
    else:
        msg = "capabilities must be a frozenset or JSON list of capability names"
        raise TypeError(msg)
    unknown = items - CAPABILITY_VALUES
    if unknown:
        msg = f"unknown capabilities: {', '.join(sorted(unknown))}"
        raise ValueError(msg)
    return items


CapabilitiesField = Annotated[
    frozenset[str],
    BeforeValidator(_coerce_capabilities),
    PlainSerializer(lambda value: sorted(value), return_type=list[str]),
]


class ProviderConfig(BaseModel):
    """One configured OpenAI-compatible provider, typed for harness use.

    API keys are read through ``api_key_env`` at emit/use time and are never
    stored on this model (convention 5 / HA1).

    ``model_id``, ``adapter``, ``extra_options``, and ``context_limit`` are
    declared target-API fields. The env-derived constructors currently leave
    them at defaults; ``require_capabilities`` is the D12 fail-closed gate and
    is not yet called from a production harness path.
    """

    model_config = ConfigDict(frozen=True)

    provider_id: str
    model_id: str = ""
    base_url: str
    api_key_env: str
    adapter: str = "openai-compatible"
    capabilities: CapabilitiesField = Field(default_factory=lambda: _DEFAULT_GATEWAY_CAPABILITIES)
    extra_options: dict[str, Any] = Field(default_factory=dict)
    context_limit: int | None = None

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        stripped = value.strip()
        parsed = urlparse(stripped)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            msg = "base_url must be an http(s) URL"
            raise ValueError(msg)
        return stripped


@dataclass(frozen=True, slots=True)
class GatewayPreset:
    """One named OpenAI-compatible inference gateway (seed metadata only)."""

    provider_id: str
    api_key_env: str
    base_url_env: str
    default_base_url: str


# Named gateway presets were removed in BE #481 — operators register providers
# in config instead. The dict remains for typing/back-compat imports.
GATEWAY_PRESETS: dict[str, GatewayPreset] = {}


def require_capabilities(config: ProviderConfig, required: frozenset[str]) -> None:
    """Fail closed when ``config`` lacks a declared capability (D12).

    Production harnesses do not call this yet; HA1 lands the gate so a later
    wiring wave can require capabilities at resolve time without a new type.
    """
    from mergecraft.main import _ConfigurationError

    missing = required - config.capabilities
    if missing:
        names = ", ".join(sorted(missing))
        msg = f"provider {config.provider_id!r} missing required capabilities: {names}"
        raise _ConfigurationError(msg)


def _has_env(name: str) -> bool:
    val = os.environ.get(name)
    return isinstance(val, str) and bool(val.strip())


def has_custom_provider_env() -> bool:
    """Return whether both generic custom-provider env vars are set."""
    return _has_env(CUSTOM_PROVIDER_BASE_URL_ENV) and _has_env(CUSTOM_PROVIDER_API_KEY_ENV)


def has_gateway_credentials(provider_id: str) -> bool:
    """Return whether ``provider_id`` can authenticate from generic custom env."""
    if has_custom_provider_env():
        return True
    from mergecraft.config.runtime_provider_registry import has_registry_credentials
    from mergecraft.config.settings import load_repo_settings

    settings = load_repo_settings(root=Path.cwd(), load_learnings_files=False)
    return has_registry_credentials(settings, provider_id.lower())


def resolve_gateway_endpoint(model: str | None) -> tuple[str, str, str] | None:
    """Resolve ``(provider_id, base_url, api_key)`` for an OpenAI-compatible model.

    Preference order:

    1. Operator registry row for the model prefix
    2. Explicit ``MERGECRAFT_CUSTOM_PROVIDER_*`` pair (any ``provider/model`` slug)

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

    from mergecraft.config.runtime_provider_registry import resolve_registry_gateway_endpoint
    from mergecraft.config.settings import load_repo_settings

    settings = load_repo_settings(root=Path.cwd(), load_learnings_files=False)
    registry_endpoint = resolve_registry_gateway_endpoint(model, settings=settings)
    if registry_endpoint is not None:
        return registry_endpoint

    custom_base = os.environ.get(CUSTOM_PROVIDER_BASE_URL_ENV, "").strip()
    custom_key = os.environ.get(CUSTOM_PROVIDER_API_KEY_ENV, "").strip()
    if custom_base and custom_key:
        return provider_id, custom_base, custom_key

    return None


def _parse_extra_options_env(env_name: str) -> dict[str, Any]:
    """Parse a JSON object env var into ``extra_options``; missing/invalid → ``{}``."""
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.debug("invalid {} JSON: {}", env_name, exc)
        return {}
    if not isinstance(parsed, dict):
        logger.debug("{} must be a JSON object, got {}", env_name, type(parsed).__name__)
        return {}
    return parsed


def _extra_options_for_provider(
    provider_id: str, *, indexed_env: str | None = None
) -> dict[str, Any]:
    """Resolve ``extra_options`` for one provider from env (O4 / #295).

    Precedence:
    1. Indexed ``MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS_<N>`` when supplied.
    2. Singleton ``MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS``.
    3. Per-provider entry in ``MERGECRAFT_PROVIDER_EXTRA_OPTIONS`` JSON map.
    """
    if indexed_env is not None:
        indexed = _parse_extra_options_env(indexed_env)
        if indexed:
            return indexed
    singleton = _parse_extra_options_env(CUSTOM_PROVIDER_EXTRA_OPTIONS_ENV)
    if singleton:
        return singleton
    by_provider = _parse_extra_options_env(PROVIDER_EXTRA_OPTIONS_ENV)
    provider_entry = by_provider.get(provider_id)
    if isinstance(provider_entry, dict):
        return provider_entry
    return {}


def _provider_config_from_env_pair(
    *,
    provider_id: str,
    base_url: str,
    api_key_env: str,
    extra_options_env: str | None = None,
) -> ProviderConfig:
    return ProviderConfig(
        provider_id=provider_id,
        base_url=base_url,
        api_key_env=api_key_env,
        extra_options=_extra_options_for_provider(provider_id, indexed_env=extra_options_env),
    )


def _resolve_indexed_providers() -> dict[str, ProviderConfig]:
    """Enumerate ``MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}_<N>`` pairs.

    Returns a dict keyed by provider id (``"provider_<N>"``). Both halves of a
    numeric suffix must be set with non-empty values; partial pairs are
    dropped, never half-emitted. The numeric ordering of indices is
    preserved — gaps are not renumbered.
    """
    by_index: dict[int, tuple[str, str]] = {}
    for key, value in os.environ.items():
        match = INDEXED_CUSTOM_PROVIDER_BASE_URL_RE.match(key)
        if match is not None:
            n = int(match.group(1))
            stripped = value.strip()
            if not stripped:
                continue
            base_url, api_key = by_index.get(n, ("", ""))
            by_index[n] = (stripped, api_key)
            continue
        match = INDEXED_CUSTOM_PROVIDER_API_KEY_RE.match(key)
        if match is not None:
            n = int(match.group(1))
            stripped = value.strip()
            if not stripped:
                continue
            base_url, api_key = by_index.get(n, ("", ""))
            by_index[n] = (base_url, stripped)
    out: dict[str, ProviderConfig] = {}
    for n in sorted(by_index):
        base_url, api_key = by_index[n]
        if not base_url or not api_key:
            # Partial pair — drop silently.
            continue
        provider_id = INDEXED_PROVIDER_ID_FMT.format(n=n)
        out[provider_id] = _provider_config_from_env_pair(
            provider_id=provider_id,
            base_url=base_url,
            api_key_env=f"MERGECRAFT_CUSTOM_PROVIDER_API_KEY_{n}",
            extra_options_env=INDEXED_CUSTOM_PROVIDER_EXTRA_OPTIONS_FMT.format(n=n),
        )
    return out


def _resolve_singleton_provider() -> ProviderConfig | None:
    """Back-compat alias for a single ``default`` provider.

    Returns ``None`` if either half of the singleton pair is missing or empty.
    """
    base_url = os.environ.get(CUSTOM_PROVIDER_BASE_URL_ENV, "").strip()
    api_key = os.environ.get(CUSTOM_PROVIDER_API_KEY_ENV, "").strip()
    if not base_url or not api_key:
        return None
    return _provider_config_from_env_pair(
        provider_id=SINGLETON_PROVIDER_ID,
        base_url=base_url,
        api_key_env=CUSTOM_PROVIDER_API_KEY_ENV,
    )


def resolve_gateway_endpoints() -> dict[str, ProviderConfig]:
    """Return every configured OpenAI-compatible provider, keyed by provider id.

    Multi-provider resolver (W3 / issue #71). The returned dict carries all
    providers the environment currently configures:

    - Indexed pairs ``MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}_<N>``
      for ``N >= 1``, with provider ids ``"provider_<N>"``.
    - The singleton ``MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}`` pair
      (PR #79 / D7 back-compat alias), as a single ``"default"`` provider.

    Precedence: **indexed pairs win**. When any indexed pair is present the
    singleton is ignored — the ``"default"`` id is reserved for
    singleton-only deployments so the two surfaces never silently merge.

    Discovery preserves gaps in the numeric suffix sequence
    (``_1`` + ``_3`` set, ``_2`` absent → ``provider_1`` and ``provider_3``
    present, ``provider_2`` absent). Partial indexed pairs (only one half
    set) are dropped, never half-emitted.
    """
    indexed = _resolve_indexed_providers()
    if indexed:
        return indexed
    singleton = _resolve_singleton_provider()
    if singleton is None:
        return {}
    return {singleton.provider_id: singleton}


def _provider_config_for_model(model: str) -> ProviderConfig | None:
    """Return the configured ``ProviderConfig`` for ``provider/model``, if any."""
    slash = model.find("/")
    if slash <= 0:
        return None
    provider_id = model[:slash].lower()

    endpoints = resolve_gateway_endpoints()
    config = endpoints.get(provider_id)
    if config is None and len(endpoints) == 1:
        config = next(iter(endpoints.values()))
    if config is not None:
        return config

    resolved = resolve_gateway_endpoint(model)
    if resolved is None:
        return None
    preset_provider_id, base_url, _api_key = resolved
    api_key_env = (
        f"LLM_PROVIDER_{_registry_env_index_for_provider(preset_provider_id)}_API_KEY"
        if _registry_env_index_for_provider(preset_provider_id) is not None
        else CUSTOM_PROVIDER_API_KEY_ENV
    )
    return ProviderConfig(
        provider_id=preset_provider_id,
        base_url=base_url,
        api_key_env=api_key_env,
        extra_options=_extra_options_for_provider(preset_provider_id),
    )


def _registry_env_index_for_provider(provider_id: str) -> int | None:
    from mergecraft.config.runtime_provider_registry import lookup_registry_entry
    from mergecraft.config.settings import load_repo_settings

    entry = lookup_registry_entry(
        load_repo_settings(root=Path.cwd(), load_learnings_files=False), provider_id
    )
    if entry is None:
        return None
    return entry.env_index


def resolve_model_params_for_model(model: str | None) -> ModelParams | None:
    """Resolve request knobs from a configured gateway's ``extra_options`` (O4)."""
    if not model:
        return None
    from mergecraft.tracing.genai import ModelParams, model_params_from_mapping

    config = _provider_config_for_model(model)
    if config is None or not config.extra_options:
        return None
    params = model_params_from_mapping(config.extra_options)
    return None if params == ModelParams() else params


__all__ = [
    "CAPABILITY_VALUES",
    "CUSTOM_PROVIDER_API_KEY_ENV",
    "CUSTOM_PROVIDER_BASE_URL_ENV",
    "GATEWAY_PRESETS",
    "SINGLETON_PROVIDER_ID",
    "GatewayPreset",
    "ProviderConfig",
    "has_custom_provider_env",
    "has_gateway_credentials",
    "require_capabilities",
    "resolve_gateway_endpoint",
    "resolve_gateway_endpoints",
    "resolve_model_params_for_model",
]
