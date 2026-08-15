"""Known OpenAI-compatible gateways (Nous Portal, Tencent TokenHub).

These providers are reached through the opencode harness via
``@ai-sdk/openai-compatible``. Callers may still set
``MERGECRAFT_CUSTOM_PROVIDER_BASE_URL`` + ``MERGECRAFT_CUSTOM_PROVIDER_API_KEY``
to override any preset; when those are absent, model prefixes ``nous/`` and
``tokenhub/`` resolve from ``NOUS_API_KEY`` / ``TOKENHUB_API_KEY``.

W3 (issue #71) extends the contract so a workflow can wire several
OpenAI-compatible providers simultaneously — each addressed by an indexed
``MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}_<N>`` env-var pair (operator
locked). The single-provider shape (and the named-preset paths) are
preserved; the multi-provider resolver adds a dict-valued surface that both
``agents/opencode.py`` and ``agents/codex.py`` consume.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Annotated, Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.functional_serializers import PlainSerializer
from pydantic.functional_validators import BeforeValidator

NOUS_API_KEY_ENV = "NOUS_API_KEY"
NOUS_BASE_URL_ENV = "NOUS_BASE_URL"
DEFAULT_NOUS_BASE_URL = "https://inference-api.nousresearch.com/v1"

TOKENHUB_API_KEY_ENV = "TOKENHUB_API_KEY"
TOKENHUB_BASE_URL_ENV = "TOKENHUB_BASE_URL"
DEFAULT_TOKENHUB_BASE_URL = "https://tokenhub-intl.tencentcloudmaas.com/v1"

CUSTOM_PROVIDER_BASE_URL_ENV = "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL"
CUSTOM_PROVIDER_API_KEY_ENV = "MERGECRAFT_CUSTOM_PROVIDER_API_KEY"

# W6 (#34): MiniMax is reachable through the existing custom-provider helper
# (operator-locked D10 / option ii). The alias env vars re-use the D7
# singleton names so the operator's mental model stays uniform with the
# generic custom-provider surface; the default base URL pins the
# OpenAI-compatible endpoint documented at
# https://platform.minimax.io/docs/api-reference/text-openai-api.md.
MINIMAX_API_KEY_ENV = CUSTOM_PROVIDER_API_KEY_ENV
MINIMAX_BASE_URL_ENV = CUSTOM_PROVIDER_BASE_URL_ENV
DEFAULT_MINIMAX_BASE_URL = "https://api.minimax.io/v1"

# Indexed multi-provider convention (W3 / issue #71). Both halves must be
# set per index; partial pairs are dropped. Discovery enumerates every
# matching env-var suffix and pairs by numeric N. Gaps are preserved
# (no renumbering).
INDEXED_CUSTOM_PROVIDER_BASE_URL_RE = re.compile(r"^MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_(\d+)$")
INDEXED_CUSTOM_PROVIDER_API_KEY_RE = re.compile(r"^MERGECRAFT_CUSTOM_PROVIDER_API_KEY_(\d+)$")
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


def require_capabilities(config: ProviderConfig, required: frozenset[str]) -> None:
    """Fail closed when ``config`` lacks a declared capability (D12)."""
    from mergecraft.main import _ConfigurationError

    missing = required - config.capabilities
    if missing:
        names = ", ".join(sorted(missing))
        msg = f"provider {config.provider_id!r} missing required capabilities: {names}"
        raise _ConfigurationError(msg)


@dataclass(frozen=True, slots=True)
class GatewayPreset:
    """One named OpenAI-compatible inference gateway."""

    provider_id: str
    api_key_env: str
    base_url_env: str
    default_base_url: str


@dataclass(frozen=True, slots=True)
class ProviderRecord:
    """One configured OpenAI-compatible provider, sourced from env vars.

    Carries the env-var names (``base_url_env`` / ``api_key_env``) that sourced
    the resolved values so loguru redaction can target the env-var *names*
    rather than the resolved key values (convention 7 / D11). The resolved
    ``api_key`` is never logged by the harness writers — this record exists so
    the writers can pass the env-var name to a redactor and still call the
    resolved value to populate a generated config file.
    """

    provider_id: str
    base_url: str
    api_key: str
    base_url_env: str
    api_key_env: str


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
    "minimax": GatewayPreset(
        provider_id="minimax",
        api_key_env=MINIMAX_API_KEY_ENV,
        base_url_env=MINIMAX_BASE_URL_ENV,
        default_base_url=DEFAULT_MINIMAX_BASE_URL,
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


def _provider_config_from_env_pair(
    *,
    provider_id: str,
    base_url: str,
    api_key_env: str,
) -> ProviderConfig:
    return ProviderConfig(
        provider_id=provider_id,
        base_url=base_url,
        api_key_env=api_key_env,
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


__all__ = [
    "CAPABILITY_VALUES",
    "CUSTOM_PROVIDER_API_KEY_ENV",
    "CUSTOM_PROVIDER_BASE_URL_ENV",
    "DEFAULT_MINIMAX_BASE_URL",
    "DEFAULT_NOUS_BASE_URL",
    "DEFAULT_TOKENHUB_BASE_URL",
    "GATEWAY_PRESETS",
    "MINIMAX_API_KEY_ENV",
    "MINIMAX_BASE_URL_ENV",
    "NOUS_API_KEY_ENV",
    "NOUS_BASE_URL_ENV",
    "SINGLETON_PROVIDER_ID",
    "TOKENHUB_API_KEY_ENV",
    "TOKENHUB_BASE_URL_ENV",
    "GatewayPreset",
    "ProviderConfig",
    "ProviderRecord",
    "has_custom_provider_env",
    "has_gateway_credentials",
    "require_capabilities",
    "resolve_gateway_endpoint",
    "resolve_gateway_endpoints",
]
