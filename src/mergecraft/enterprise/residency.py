"""Data-residency controls for enterprise deployments (#381).

Wraps ``mergecraft.agents.provider_health.enforce_residency`` (#371).

Exports:
    DataResidencyPolicy: Pydantic model declaring allowed regions.
    enforce_data_residency: Raise PermissionError when a region is disallowed.
"""

from __future__ import annotations

from pydantic import BaseModel

from mergecraft.agents.provider_health import enforce_residency

__all__ = [
    "DataResidencyPolicy",
    "enforce_data_residency",
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
