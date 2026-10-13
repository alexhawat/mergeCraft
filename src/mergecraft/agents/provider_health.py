"""Provider capability catalog and residency checks (#371).

The bundled capability catalog names, per model, the context size, reasoning
and tool support, structured-output support, cost and latency class, and data
residency the enterprise runtime reads when it enforces region-aware routing.
The residency allow-list check refuses a region the policy does not permit.

Exports:
    capability_catalog: Capability rows for the bundled models.
    enforce_residency: Refuse a region outside the allowed set.
"""

from __future__ import annotations

from typing import Any, Final

_CAPABILITY_CATALOG: Final[tuple[dict[str, Any], ...]] = (
    {
        "id": "anthropic/claude-opus",
        "context_size": 200_000,
        "reasoning": True,
        "tool_support": True,
        "structured_output": True,
        "cost": "high",
        "latency": "high",
        "data_residency": "us-east-1",
    },
    {
        "id": "anthropic/claude-sonnet",
        "context_size": 200_000,
        "reasoning": True,
        "tool_support": True,
        "structured_output": True,
        "cost": "medium",
        "latency": "medium",
        "data_residency": "us-east-1",
    },
    {
        "id": "anthropic/claude-haiku",
        "context_size": 200_000,
        "reasoning": False,
        "tool_support": True,
        "structured_output": True,
        "cost": "low",
        "latency": "low",
        "data_residency": "us-east-1",
    },
    {
        "id": "openai/gpt-5.3-codex",
        "context_size": 128_000,
        "reasoning": True,
        "tool_support": True,
        "structured_output": True,
        "cost": "medium",
        "latency": "medium",
        "data_residency": "us-east-1",
    },
)


def capability_catalog() -> list[dict[str, Any]]:
    """Return catalog rows with context, reasoning, tools, structured IO, cost, latency, residency."""
    return [dict(row) for row in _CAPABILITY_CATALOG]


def enforce_residency(*, region: str, allowed: tuple[str, ...] | list[str]) -> None:
    """Refuse a region that is not in the residency allow-list.

    Args:
        region: Requested processing region.
        allowed: Regions the residency policy permits.

    Raises:
        PermissionError: ``region`` is outside the allowed residency set.
    """
    permitted = {str(item) for item in allowed}
    if str(region) not in permitted:
        msg = f"residency policy forbids region {region!r}; allowed={sorted(permitted)}"
        raise PermissionError(msg)


__all__ = [
    "capability_catalog",
    "enforce_residency",
]
