"""Org memory distribution without a dashboard (#381, D6).

Wraps ``mergecraft.memory`` — does not re-author it.

Exports:
    bind_org_memory: Bind an org memory backend for dashboard-free distribution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mergecraft.memory import OrganizationMemoryBackend

__all__ = [
    "bind_org_memory",
]


def bind_org_memory(
    backend: OrganizationMemoryBackend,
    *,
    dashboard_url: str | None,
) -> OrganizationMemoryBackend:
    """Bind *backend* for org memory distribution without a dashboard.

    Memory distribution is **file/API-only** — a dashboard URL is refused so
    the workflow cannot depend on a dashboard being available (#381).

    Args:
        backend: An existing :class:`~mergecraft.memory.OrganizationMemoryBackend`
            instance (e.g. ``LocalMemoryBackend``).
        dashboard_url: Must be ``None``.  Passing a non-``None`` value raises
            ``ValueError``.

    Returns:
        The same *backend* instance, usable for ``put`` / ``get`` / ``list``.

    Raises:
        ValueError: When *dashboard_url* is not ``None``.
    """
    if dashboard_url is not None:
        msg = (
            "memory distribution via a dashboard URL is not supported — "
            "distribution must work without a dashboard (#381)"
        )
        raise ValueError(msg)
    return backend
