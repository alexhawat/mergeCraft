"""Bind and enforce enterprise controls against a live review process (#381).

Call :func:`bind_enterprise_from_settings` when repo settings are loaded or
a tracer is constructed. Bound state is process-local (a :class:`ContextVar`)
so tests can isolate it.

Exports:
    bind_enterprise_from_settings: Apply proxy, CA, telemetry, residency, retention.
    current_enterprise_settings: Return the bound block (or inert defaults).
    remote_export_allowed: Whether Logfire/OTLP export may run.
    effective_retention_days: Optional enterprise override for JSONL retention.
    enforce_routed_model_residency: Fail closed when a routed model is out of region.
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
    "bind_enterprise_from_settings",
    "current_enterprise_settings",
    "effective_retention_days",
    "enforce_routed_model_residency",
    "remote_export_allowed",
    "reset_enterprise_runtime",
]

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


def bind_enterprise_from_settings(settings: RepoSettings | EnterpriseSettings) -> None:
    """Bind *settings* and apply proxy / CA side effects to this process.

    Args:
        settings: A :class:`RepoSettings` (uses its ``enterprise`` field) or an
            :class:`EnterpriseSettings` block directly.
    """
    block = (
        settings
        if isinstance(settings, EnterpriseSettings)
        else getattr(settings, "enterprise", EnterpriseSettings())
    )
    _BOUND.set(block)
    if block.https_proxy:
        apply_enterprise_proxy(ProxyConfig(https_proxy=block.https_proxy, no_proxy=block.no_proxy))
    if block.ca_file:
        ca_path = Path(block.ca_file)
        load_custom_ca(ca_path)
        os.environ["SSL_CERT_FILE"] = str(ca_path)
        os.environ["REQUESTS_CA_BUNDLE"] = str(ca_path)


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

    Args:
        model_id: Catalog model id chosen by routing.
        catalog: Optional catalog rows; defaults to :func:`capability_catalog`.

    Raises:
        PermissionError: The model's ``data_residency`` is not allowed.
    """
    allowed = current_enterprise_settings().allowed_regions
    if not allowed:
        return
    rows = catalog
    if rows is None:
        from mergecraft.agents.provider_health import capability_catalog

        rows = capability_catalog()
    region = "unknown"
    for row in rows:
        if str(row.get("id")) == model_id:
            region = str(row.get("data_residency") or "unknown")
            break
    enforce_data_residency(region=region, policy=DataResidencyPolicy(allowed=allowed))
