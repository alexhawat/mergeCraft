"""Bind and enforce enterprise controls against a live review process (#381).

Call :func:`bind_enterprise_after_trust` after trust-tier resolution — never
during YAML parse. Bound state is process-local (a :class:`ContextVar`) so
tests can isolate it.

Exports:
    bind_enterprise_from_settings: Apply proxy, CA, telemetry, residency, retention.
    bind_enterprise_after_trust: Bind after trust; skip network mutations when untrusted.
    current_enterprise_settings: Return the bound block (or inert defaults).
    remote_export_allowed: Whether Logfire/OTLP export may run.
    effective_retention_days: Optional enterprise override for JSONL retention.
    enforce_routed_model_residency: Fail closed when a routed model is out of region.
    agent_network_env: Proxy/CA vars to copy into provider subprocess env.
    reset_enterprise_runtime: Clear bound state (tests).
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mergecraft.enterprise.certificates import load_custom_ca
from mergecraft.enterprise.controls import EnterpriseSettings
from mergecraft.enterprise.proxy import ProxyConfig, apply_enterprise_proxy
from mergecraft.enterprise.residency import DataResidencyPolicy, enforce_data_residency
from mergecraft.enterprise.telemetry import (
    is_telemetry_export_enabled,
    resolve_telemetry_mode,
)

if TYPE_CHECKING:
    from mergecraft.config.settings import RepoSettings

__all__ = [
    "agent_network_env",
    "bind_enterprise_after_trust",
    "bind_enterprise_from_settings",
    "current_enterprise_settings",
    "effective_retention_days",
    "enforce_routed_model_residency",
    "remote_export_allowed",
    "reset_enterprise_runtime",
]

_AGENT_NETWORK_ENV: tuple[str, ...] = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
)

_BOUND: ContextVar[EnterpriseSettings | None] = ContextVar(
    "mergecraft_enterprise_settings",
    default=None,
)


def current_enterprise_settings() -> EnterpriseSettings:
    """Return the bound enterprise block, or inert defaults when unbound."""
    bound = _BOUND.get()
    return bound if bound is not None else EnterpriseSettings()


def reset_enterprise_runtime() -> None:
    """Clear bound enterprise controls (test isolation)."""
    _BOUND.set(None)


def bind_enterprise_from_settings(
    settings: RepoSettings | EnterpriseSettings,
    *,
    apply_network: bool = True,
) -> None:
    """Bind *settings* and optionally apply proxy / CA side effects.

    Args:
        settings: A :class:`RepoSettings` (uses its ``enterprise`` field) or an
            :class:`EnterpriseSettings` block directly.
        apply_network: When ``False``, bind telemetry/residency/retention only.
            Proxy and CA must not be applied from untrusted repo config.
    """
    block = (
        settings
        if isinstance(settings, EnterpriseSettings)
        else getattr(settings, "enterprise", EnterpriseSettings())
    )
    _BOUND.set(block)
    if not apply_network:
        return
    if block.https_proxy:
        apply_enterprise_proxy(ProxyConfig(https_proxy=block.https_proxy, no_proxy=block.no_proxy))
    if block.ca_file:
        ca_path = Path(block.ca_file)
        load_custom_ca(ca_path)
        os.environ["SSL_CERT_FILE"] = str(ca_path)
        os.environ["REQUESTS_CA_BUNDLE"] = str(ca_path)


def bind_enterprise_after_trust(settings: RepoSettings, tier: str) -> None:
    """Bind enterprise controls after trust resolution.

    Untrusted checkouts never mutate ``HTTPS_PROXY`` / CA env vars.
    """
    bind_enterprise_from_settings(settings, apply_network=(tier == "trusted"))


def agent_network_env() -> dict[str, str]:
    """Return bound proxy/CA variables present on the parent process.

    :func:`mergecraft.utils.secrets.build_agent_env` default-denies these
    names; callers must copy the mapping into each provider child env.
    """
    exported: dict[str, str] = {}
    for key in _AGENT_NETWORK_ENV:
        value = os.environ.get(key, "").strip()
        if value:
            exported[key] = value
    return exported


def remote_export_allowed() -> bool:
    """Return whether remote tracing export (Logfire / OTLP) is permitted."""
    mode = resolve_telemetry_mode(explicit=current_enterprise_settings().telemetry)
    return is_telemetry_export_enabled(mode)


def effective_retention_days() -> int | None:
    """Return the enterprise retention override, or ``None`` to keep tracing defaults."""
    return current_enterprise_settings().retention_days


def enforce_routed_model_residency(
    model_id: str,
    *,
    catalog: list[dict[str, Any]] | None = None,
) -> None:
    """Refuse *model_id* when a non-empty residency allow-list is bound.

    Regions are resolved from :func:`mergecraft.models.lookup_model_data_residency`
    (the support-matrix ``PROVIDERS`` catalog). The routing capability catalog
    is a fallback for ids that catalog still lists. Unknown ids are
    ``unknown`` and fail closed.

    Args:
        model_id: Catalog model id chosen by routing.
        catalog: Optional capability-catalog rows when PROVIDERS has no match.

    Raises:
        PermissionError: The model's ``data_residency`` is not allowed.
    """
    allowed = current_enterprise_settings().allowed_regions
    if not allowed:
        return
    from mergecraft.models import lookup_model_data_residency

    region = lookup_model_data_residency(model_id) or "unknown"
    if region == "unknown":
        rows = catalog
        if rows is None:
            from mergecraft.agents.provider_health import capability_catalog

            rows = capability_catalog()
        for row in rows:
            if str(row.get("id")) == model_id:
                region = str(row.get("data_residency") or "unknown")
                break
    enforce_data_residency(region=region, policy=DataResidencyPolicy(allowed=allowed))
