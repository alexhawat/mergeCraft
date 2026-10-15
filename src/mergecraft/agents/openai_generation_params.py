"""Map OpenAI-compatible generation knobs for OpenCode and direct HTTP paths (#983)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mergecraft.agents.curated_model_catalog import (
    merge_curated_generation_defaults,
    positive_int_option,
    require_output_cap_for_model,
)


def normalize_generation_extra_options(
    model: str | None,
    extra_options: dict[str, Any],
) -> dict[str, Any]:
    """Merge catalog defaults and alias ``max_completion_tokens`` to ``max_tokens``."""
    merged = merge_curated_generation_defaults(model, dict(extra_options))
    cap = positive_int_option(merged.get("max_completion_tokens"))
    if cap is not None and positive_int_option(merged.get("max_tokens")) is None:
        merged["max_tokens"] = cap
    return merged


@dataclass(frozen=True, slots=True)
class OpenAIGenerationParams:
    """Generation parameters for OpenAI-compatible chat/responses requests."""

    max_completion_tokens: int | None = None
    reasoning_effort: str | None = None
    max_tokens: int | None = None


def resolve_openai_generation_params(
    model: str | None,
    extra_options: dict[str, Any],
) -> OpenAIGenerationParams:
    """Resolve generation params after catalog merge and aliasing."""
    merged = normalize_generation_extra_options(model, extra_options)
    cap = positive_int_option(merged.get("max_completion_tokens"))
    if cap is None:
        cap = positive_int_option(merged.get("max_tokens"))
    effort_raw = merged.get("reasoning_effort")
    effort = str(effort_raw).strip() if effort_raw else None
    max_tokens = positive_int_option(merged.get("max_tokens"))
    return OpenAIGenerationParams(
        max_completion_tokens=cap,
        reasoning_effort=effort or None,
        max_tokens=max_tokens,
    )


def openai_chat_completion_body_fields(
    model: str | None,
    extra_options: dict[str, Any],
) -> dict[str, Any]:
    """Build OpenAI Chat Completions fields for *model* (direct HTTP path)."""
    params = resolve_openai_generation_params(model, extra_options)
    body: dict[str, Any] = {}
    if params.max_completion_tokens is not None:
        body["max_completion_tokens"] = params.max_completion_tokens
    elif params.max_tokens is not None:
        body["max_tokens"] = params.max_tokens
    if params.reasoning_effort:
        body["reasoning_effort"] = params.reasoning_effort
    return body


def validate_generation_params_for_model(model: str | None, extra_options: dict[str, Any]) -> None:
    """Validate generation params; raises ``ValueError`` when misconfigured."""
    normalized = normalize_generation_extra_options(model, extra_options)
    require_output_cap_for_model(model, normalized)


__all__ = [
    "OpenAIGenerationParams",
    "normalize_generation_extra_options",
    "openai_chat_completion_body_fields",
    "positive_int_option",
    "resolve_openai_generation_params",
    "validate_generation_params_for_model",
]
