"""Data-residency controls for enterprise deployments (#381).

Wraps ``mergecraft.agents.provider_health.enforce_residency`` (#371).

Exports:
    DataResidencyPolicy: Pydantic model declaring allowed regions.
    enforce_data_residency: Raise PermissionError when a region is disallowed.
    trace_sink_region: The region a remote trace sink entry exports to, if known.
    trace_export_refusal: Why a remote trace sink is outside the allow-list, or ``None``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from mergecraft.agents.provider_health import enforce_residency

__all__ = [
    "DataResidencyPolicy",
    "enforce_data_residency",
    "trace_export_refusal",
    "trace_sink_region",
]


class DataResidencyPolicy(BaseModel):
    """Declare which regions are permitted for data processing.

    Attributes:
        allowed: Tuple of permitted region identifiers.  An empty tuple
            fails closed (every region is refused).
    """

    allowed: tuple[str, ...]


def enforce_data_residency(*, region: str, policy: DataResidencyPolicy) -> None:
    """Raise ``PermissionError`` when *region* is not on the allow-list.

    Args:
        region: The region identifier to check.
        policy: The residency policy containing the allowed-region list.

    Raises:
        PermissionError: When *region* is not in ``policy.allowed`` (fail closed
            on an empty allow-list).
    """
    enforce_residency(region=region, allowed=policy.allowed)


def trace_sink_region(entry: Any) -> str | None:
    """Return the region a remote trace sink entry exports to, or ``None`` when undeclared.

    A ``logfire`` sink exports to its ``region`` ingest host (``us`` by default)
    unless an ``endpoint`` overrides the host, in which case the region is not
    known. An ``otel`` sink's region is known only when the entry declares
    ``region`` explicitly; the field's default is not a declaration.

    Args:
        entry: A ``TraceSinkEntry`` of type ``logfire`` or ``otel``.

    Returns:
        str | None: The declared or implied region, or ``None``.
    """
    sink_type = getattr(entry, "type", None)
    region = getattr(entry, "region", None)
    if sink_type == "logfire":
        if getattr(entry, "endpoint", None):
            return None
        return str(region or "us")
    if sink_type == "otel":
        fields_set: set[str] = getattr(entry, "model_fields_set", set())
        return str(region) if region and "region" in fields_set else None
    return None


def _region_permitted(region: str, allowed: tuple[str, ...]) -> bool:
    """``region`` is allowed when an entry names it or one of its sub-regions (``eu-west-1``)."""
    return any(item == region or item.startswith(f"{region}-") for item in allowed)


def trace_export_refusal(entry: Any, allowed: tuple[str, ...]) -> str | None:
    """Return why a remote trace sink is outside the residency allow-list, or ``None``.

    An empty ``allowed`` declares no residency policy. Otherwise a sink whose
    region is undeclared is refused, and a declared region is permitted when an
    allow-list entry equals it or starts with ``<region>-`` (``eu`` matches
    ``eu-west-1``).

    Args:
        entry: A ``TraceSinkEntry`` of type ``logfire`` or ``otel``.
        allowed: The bound residency allow-list.

    Returns:
        str | None: A refusal reason naming the sink type and region, or ``None``.
    """
    if not allowed:
        return None
    sink_type = getattr(entry, "type", None)
    region = trace_sink_region(entry)
    if region is None:
        return (
            f"residency policy: the {sink_type} trace sink declares no region; "
            f"allowed={sorted(allowed)}"
        )
    if _region_permitted(region, allowed):
        return None
    return (
        f"residency policy forbids {sink_type} trace export to region {region!r}; "
        f"allowed={sorted(allowed)}"
    )
