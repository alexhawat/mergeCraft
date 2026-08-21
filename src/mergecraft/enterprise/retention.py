"""Trace retention and privacy-log policy for enterprise deployments (#381).

Exports:
    PrivacyLogMode: Enum of supported privacy logging modes.
    TraceRetentionPolicy: Dataclass for trace retention configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "PrivacyLogMode",
    "TraceRetentionPolicy",
]


class PrivacyLogMode(StrEnum):
    """Privacy mode for log content.

    Attributes:
        STANDARD: Full log content; no special scrubbing.
        PRIVACY_AWARE: PII / credential fields are suppressed before storage.
    """

    STANDARD = "standard"
    PRIVACY_AWARE = "privacy_aware"


@dataclass
class TraceRetentionPolicy:
    """Trace retention configuration.

    Attributes:
        days: Number of days to retain traces.  Must be positive.
        privacy_mode: Privacy logging mode applied during retention.

    Raises:
        ValueError: When *days* is zero or negative.
    """

    days: int
    privacy_mode: PrivacyLogMode

    def __post_init__(self) -> None:
        if self.days <= 0:
            msg = f"retention days must be a positive integer, got: {self.days}"
            raise ValueError(msg)
