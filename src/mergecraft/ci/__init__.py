"""CI pipeline intelligence — providers, normalization, and fingerprints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.ci.normalize import normalize_failure

if TYPE_CHECKING:
    from mergecraft.ci.providers import PipelineProvider

__all__ = ["get_provider", "normalize_failure"]


def get_provider(provider_id: str) -> PipelineProvider:
    """Lazy registry lookup to avoid import cycles with MCP tools."""
    from mergecraft.ci.providers import get_provider as _get_provider

    return _get_provider(provider_id)
