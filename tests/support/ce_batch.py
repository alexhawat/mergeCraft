"""Shared helpers for sweep 20c Batch CE RED pins (#368-#371)."""

from __future__ import annotations

from tests.support.cd_batch import (
    d10_root_callback_owns_globals,
    module_exists,
    require_callable,
    require_module,
)
from tests.support.dead_package_wiring import SRC_ROOT

CONFIG_COMPAT_MODULE = "mergecraft.config.compat"
SPECIALIST_ECONOMICS_MODULE = "mergecraft.agents.economics"
PROVIDER_HEALTH_MODULE = "mergecraft.agents.provider_health"

CONFIG_SCHEMA_VERSION_ATTR = "CONFIG_SCHEMA_VERSION"
CE_PROFILE_NAMES = frozenset(
    {
        "fast",
        "standard",
        "deep",
        "security",
        "api_compatibility",
        "migration",
        "monorepo",
        "cross_repo",
    }
)
USAGE_ATTRS = (
    "gen_ai.usage.input_tokens",
    "gen_ai.usage.output_tokens",
    "gen_ai.usage.cache_read_input_tokens",
    "gen_ai.usage.cache_creation_input_tokens",
    "gen_ai.usage.cost_usd",
)
CAPABILITY_DIMENSIONS = frozenset(
    {
        "context_size",
        "reasoning",
        "tool_support",
        "structured_output",
        "cost",
        "latency",
        "data_residency",
    }
)
TRACING_EXPORTERS = SRC_ROOT / "tracing" / "exporters.py"


def src_mentions(*needles: str) -> list[str]:
    """Return repo-relative ``src/mergecraft`` files that mention any needle."""
    hits: list[str] = []
    lowered = tuple(needle.casefold() for needle in needles)
    for path in sorted(SRC_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8").casefold()
        if any(needle in text for needle in lowered):
            hits.append(path.relative_to(SRC_ROOT).as_posix())
    return hits


__all__ = [
    "CAPABILITY_DIMENSIONS",
    "CE_PROFILE_NAMES",
    "CONFIG_COMPAT_MODULE",
    "CONFIG_SCHEMA_VERSION_ATTR",
    "PROVIDER_HEALTH_MODULE",
    "SPECIALIST_ECONOMICS_MODULE",
    "TRACING_EXPORTERS",
    "USAGE_ATTRS",
    "d10_root_callback_owns_globals",
    "module_exists",
    "require_callable",
    "require_module",
    "src_mentions",
]
