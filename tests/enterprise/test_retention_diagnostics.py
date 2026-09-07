"""W7.1 — operational diagnostics (#381).

Intended public API (W7.2): ``mergecraft.enterprise.diagnostics``.
"""

from __future__ import annotations


def test_operational_diagnostics_report_includes_python() -> None:
    """Happy: operational diagnostics expose a python/runtime field."""
    from mergecraft.enterprise.diagnostics import operational_diagnostics

    report = operational_diagnostics()
    blob = str(report).casefold()
    assert "python" in blob
