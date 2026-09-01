"""CI pipeline intelligence — providers, normalization, and fingerprints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.ci.normalize import normalize_failure
from mergecraft.ci.sarif_ingest import (
    ci_wait_inputs_from_env,
    ingest_ci_sarif_after_ci_wait,
    ingest_ci_sarif_from_action_env,
)

if TYPE_CHECKING:
    from mergecraft.ci.providers import PipelineProvider

__all__ = [
    "ci_wait_inputs_from_env",
    "get_provider",
    "ingest_ci_sarif_after_ci_wait",
    "ingest_ci_sarif_from_action_env",
    "normalize_failure",
]


def get_provider(provider_id: str) -> PipelineProvider:
    """Lazy registry lookup to avoid import cycles with MCP tools."""
    from mergecraft.ci.providers import get_provider as _get_provider

    return _get_provider(provider_id)
