"""Curated BYOK model catalog: published pricing, defaults, and review cost (issue #983).

First-class slugs (for example ``paperinstruments/ultramarine-1-flash``) carry
USD-per-million-token rates, optional cached-input pricing, and generation
defaults used when operators configure providers through the registry alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from mergecraft.agents.shared import AgentUsage, format_cost_usd
from mergecraft.models import parse_model

_MTOK: Final[float] = 1_000_000.0


def positive_int_option(value: object) -> int | None:
    """Return a positive integer from a wire value, or ``None`` when absent/invalid."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer():
        as_int = int(value)
        return as_int if as_int > 0 else None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = int(stripped)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


PAPERINSTRUMENTS_BASE_URL: Final[str] = "https://api.paperinstruments.com/v1"
ULTRAMARINE_1_FLASH_SLUG: Final[str] = "paperinstruments/ultramarine-1-flash"


@dataclass(frozen=True, slots=True)
class CuratedModelEntry:
    """Pricing and generation defaults for one curated slug."""

    slug: str
    api_model_id: str
    input_usd_per_mtok: float
    cached_input_usd_per_mtok: float
    output_usd_per_mtok: float
    default_max_completion_tokens: int
    default_reasoning_effort: str
    requires_output_cap: bool = True
    cache_read_inclusive: bool = True


_CURATED: Final[dict[str, CuratedModelEntry]] = {
    ULTRAMARINE_1_FLASH_SLUG: CuratedModelEntry(
        slug=ULTRAMARINE_1_FLASH_SLUG,
        api_model_id="ultramarine-1-flash",
        input_usd_per_mtok=0.15,
        cached_input_usd_per_mtok=0.03,
        output_usd_per_mtok=0.50,
        default_max_completion_tokens=8192,
        default_reasoning_effort="low",
    ),
}


def curated_model_entry(slug: str | None) -> CuratedModelEntry | None:
    """Return the curated row for *slug*, or ``None`` when unknown."""
    if not slug:
        return None
    normalized = slug.strip()
    if not normalized:
        return None
    direct = _CURATED.get(normalized)
    if direct is not None:
        return direct
    provider, model_id = parse_model(normalized)
    for entry in _CURATED.values():
        if entry.slug == normalized:
            return entry
        entry_provider, _ = parse_model(entry.slug)
        if provider == entry_provider and model_id == entry.api_model_id:
            return entry
    return None


def merge_curated_generation_defaults(
    slug: str | None,
    extra_options: dict[str, object],
) -> dict[str, object]:
    """Apply catalog defaults without overriding explicit operator options."""
    entry = curated_model_entry(slug)
    if entry is None:
        return dict(extra_options)
    merged: dict[str, object] = {
        "max_completion_tokens": entry.default_max_completion_tokens,
        "reasoning_effort": entry.default_reasoning_effort,
    }
    merged.update(extra_options)
    return merged


def effective_max_output_tokens(slug: str | None, extra_options: dict[str, object]) -> int | None:
    """Return the positive output cap from *extra_options* or catalog defaults."""
    for key in ("max_completion_tokens", "max_tokens"):
        resolved = positive_int_option(extra_options.get(key))
        if resolved is not None:
            return resolved
    entry = curated_model_entry(slug)
    if entry is not None:
        return entry.default_max_completion_tokens
    return None


def require_opencode_harness_for_model(slug: str | None, harness: str) -> None:
    """Fail closed when a curated slug is used outside the OpenCode harness (#983)."""
    entry = curated_model_entry(slug)
    if entry is None:
        return
    if harness != "opencode":
        msg = (
            f"configuration error: {entry.slug} is only supported with harness: opencode "
            f"(got {harness!r})"
        )
        raise ValueError(msg)


def require_output_cap_for_model(slug: str | None, extra_options: dict[str, object]) -> None:
    """Fail closed when a curated model that requires a cap has none configured."""
    entry = curated_model_entry(slug)
    if entry is None or not entry.requires_output_cap:
        return
    if effective_max_output_tokens(slug, extra_options) is None:
        msg = (
            f"model {entry.slug!r} requires an output token cap "
            "(set max_completion_tokens or max_tokens in "
            "MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS or catalog defaults)"
        )
        raise ValueError(msg)


def compute_review_cost_usd(
    *,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int | None = None,
) -> float | None:
    """Compute USD cost from token usage and the curated price table."""
    entry = curated_model_entry(model)
    if entry is None:
        return None
    cached = max(0, cache_read_tokens or 0)
    uncached = max(0, input_tokens - cached) if entry.cache_read_inclusive else max(0, input_tokens)
    return (
        uncached * entry.input_usd_per_mtok
        + cached * entry.cached_input_usd_per_mtok
        + output_tokens * entry.output_usd_per_mtok
    ) / _MTOK


def apply_catalog_cost_to_usage(
    usage: AgentUsage | None, *, model: str | None
) -> AgentUsage | None:
    """Fill ``cost_usd`` on *usage* from the catalog when the provider omitted it."""
    if usage is None:
        return usage
    total_tokens = usage.input_tokens + usage.output_tokens + (usage.cache_read_tokens or 0)
    if total_tokens <= 0:
        if usage.cost_usd is None or usage.cost_usd <= 0:
            return usage
        return AgentUsage(
            agent=usage.agent,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            cost_usd=None,
        )
    if usage.cost_usd is not None:
        return usage
    computed = compute_review_cost_usd(
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
    )
    if computed is None or computed <= 0:
        return usage
    return AgentUsage(
        agent=usage.agent,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cost_usd=computed,
    )


def cost_summary_from_usage_entries(
    usage_entries: list[AgentUsage | object],
    *,
    budget_tracker: object | None = None,
) -> str | None:
    """Render a published cost line from per-attempt usage (curated models only)."""
    from mergecraft.utils.run_bounds import BudgetTracker

    if isinstance(budget_tracker, BudgetTracker) and budget_tracker.cost_used > 0:
        return f"${format_cost_usd(budget_tracker.cost_used)}"
    total = 0.0
    known = False
    for row in usage_entries:
        if not isinstance(row, AgentUsage):
            continue
        if row.cost_usd is not None and row.cost_usd > 0:
            total += row.cost_usd
            known = True
    if not known:
        return None
    return f"${format_cost_usd(total)}"


__all__ = [
    "PAPERINSTRUMENTS_BASE_URL",
    "ULTRAMARINE_1_FLASH_SLUG",
    "CuratedModelEntry",
    "apply_catalog_cost_to_usage",
    "compute_review_cost_usd",
    "cost_summary_from_usage_entries",
    "curated_model_entry",
    "effective_max_output_tokens",
    "merge_curated_generation_defaults",
    "require_opencode_harness_for_model",
    "require_output_cap_for_model",
]
