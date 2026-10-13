"""The provider-health module keeps only the surfaces a review path calls.

Routing, circuit-breaker, budget and routing-eval helpers had no production
caller; only :func:`capability_catalog` (enterprise routing residency fallback)
and :func:`enforce_residency` (enterprise residency policy) are reached. The
residency controls keep working.
"""

from __future__ import annotations

import pytest

from mergecraft.agents.provider_health import capability_catalog, enforce_residency

_DELETED_CALLABLES = (
    "ProviderBreaker",
    "ProviderHealth",
    "degrade_unavailable",
    "enforce_provider_budget",
    "evaluate_routing_quality",
    "manifest_provider_stamp",
    "nightly_provider_smoke",
    "resolve_required_model",
    "route_model",
    "should_retry_provider",
    "verifier_judge_models",
)
_DELETED_CONSTANTS = ("MAX_RETRY_ATTEMPTS", "RETRYABLE_FAILURES", "ROUTING_INTENTS")
_DELETED_TYPES = ("DegradeOutcome", "RoutingEvalResult", "SmokeReport")
_CAPABILITY_DIMENSIONS = (
    "context_size",
    "reasoning",
    "tool_support",
    "structured_output",
    "cost",
    "latency",
    "data_residency",
)


def test_module_exports_exactly_the_kept_surface() -> None:
    """``__all__`` names the two called surfaces and nothing else."""
    import mergecraft.agents.provider_health as module

    assert set(module.__all__) == {"capability_catalog", "enforce_residency"}
    # Surviving surface: the catalog still describes every capability dimension.
    rows = capability_catalog()
    assert rows
    for dimension in _CAPABILITY_DIMENSIONS:
        assert dimension in rows[0]


@pytest.mark.parametrize("name", [*_DELETED_CALLABLES, *_DELETED_CONSTANTS, *_DELETED_TYPES])
def test_unwired_provider_helper_is_gone(name: str) -> None:
    """A helper with no production caller is deleted; residency still refuses a region."""
    import mergecraft.agents.provider_health as module

    assert not hasattr(module, name), f"{name} has no caller and must be deleted"
    # Surviving surface: the direct residency check is intact.
    with pytest.raises(PermissionError, match=r"residen"):
        enforce_residency(region="us-east-1", allowed=("eu-central-1",))
    enforce_residency(region="us-east-1", allowed=("us-east-1", "eu-central-1"))


def test_enterprise_routed_model_residency_still_refuses_a_disallowed_region() -> None:
    """The enterprise gate still refuses an out-of-region model, via the deleted routing helper's replacement."""
    import mergecraft.agents.provider_health as module

    assert not hasattr(module, "route_model"), "route_model has no caller and must be deleted"
    from mergecraft.enterprise.controls import EnterpriseSettings
    from mergecraft.enterprise.runtime import (
        bind_enterprise_from_settings,
        enforce_routed_model_residency,
        reset_enterprise_runtime,
    )

    try:
        bind_enterprise_from_settings(EnterpriseSettings(allowed_regions=("eu-west-1",)))
        with pytest.raises(PermissionError, match=r"residen"):
            enforce_routed_model_residency("anthropic/claude-opus")
        # Surviving surface: an in-region catalog model passes the same gate.
        bind_enterprise_from_settings(EnterpriseSettings(allowed_regions=("us-east-1",)))
        enforce_routed_model_residency("anthropic/claude-opus")
    finally:
        reset_enterprise_runtime()
