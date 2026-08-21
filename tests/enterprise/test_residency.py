"""W7.1 — data-residency controls (#381).

Intended public API (W7.2): ``mergecraft.enterprise.residency``.
Distinct from ``mergecraft.agents.provider_health.enforce_residency`` (#371).
"""

from __future__ import annotations

import pytest


def test_enforce_data_residency_allows_listed_region() -> None:
    """Happy: a region on the allow-list is accepted."""
    from mergecraft.enterprise.residency import DataResidencyPolicy, enforce_data_residency

    enforce_data_residency(region="eu-west-1", policy=DataResidencyPolicy(allowed=("eu-west-1",)))


def test_enforce_data_residency_blocks_disallowed_region() -> None:
    """Error: a region outside the allow-list raises PermissionError naming residency."""
    from mergecraft.enterprise.residency import DataResidencyPolicy, enforce_data_residency

    with pytest.raises(PermissionError, match="residency"):
        enforce_data_residency(
            region="us-east-1",
            policy=DataResidencyPolicy(allowed=("eu-west-1",)),
        )


def test_enforce_data_residency_empty_allow_list_fails_closed() -> None:
    """Edge: an empty allow-list refuses every region (fail closed)."""
    from mergecraft.enterprise.residency import DataResidencyPolicy, enforce_data_residency

    with pytest.raises(PermissionError, match="residency"):
        enforce_data_residency(region="eu-west-1", policy=DataResidencyPolicy(allowed=()))


def test_enterprise_residency_is_not_provider_health_module() -> None:
    """The #381 control lives under enterprise/, wrapping rather than rewriting #371."""
    from mergecraft.enterprise import residency as enterprise_residency

    assert enterprise_residency.__name__ == "mergecraft.enterprise.residency"
    assert "agents.provider_health" not in enterprise_residency.__name__
