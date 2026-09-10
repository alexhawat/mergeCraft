"""Fixture: severity capping path touched by the planted PR."""

from __future__ import annotations

BLOCKING_SEVERITIES = frozenset({"Critical", "Major"})


def has_blocker(findings: list[object]) -> bool:
    """Return whether any finding uses a blocking severity."""
    for finding in findings:
        severity = getattr(finding, "severity", None)
        if severity in BLOCKING_SEVERITIES:
            return True
    return False
