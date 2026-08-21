"""W7.1 — trace retention and operational diagnostics (#381).

Intended public API (W7.2): ``mergecraft.enterprise.retention`` and
``mergecraft.enterprise.diagnostics``.
"""

from __future__ import annotations

import pytest


def test_trace_retention_policy_privacy_aware_mode() -> None:
    """Happy: retention accepts a positive day count and a privacy-aware log mode."""
    from mergecraft.enterprise.retention import PrivacyLogMode, TraceRetentionPolicy

    policy = TraceRetentionPolicy(days=7, privacy_mode=PrivacyLogMode.PRIVACY_AWARE)
    assert policy.days == 7
    assert policy.privacy_mode == PrivacyLogMode.PRIVACY_AWARE


@pytest.mark.parametrize("days", [0, -1])
def test_trace_retention_rejects_non_positive_days(days: int) -> None:
    """Error: zero or negative retention is refused."""
    from mergecraft.enterprise.retention import PrivacyLogMode, TraceRetentionPolicy

    with pytest.raises(ValueError, match=r"retention|days"):
        TraceRetentionPolicy(days=days, privacy_mode=PrivacyLogMode.STANDARD)


def test_operational_diagnostics_report_includes_python() -> None:
    """Happy: operational diagnostics expose a python/runtime field."""
    from mergecraft.enterprise.diagnostics import operational_diagnostics

    report = operational_diagnostics()
    blob = str(report).casefold()
    assert "python" in blob
