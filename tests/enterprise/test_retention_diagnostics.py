"""W7.1 — operational diagnostics (#381).

Intended public API (W7.2): ``mergecraft.enterprise.diagnostics``.
"""

from __future__ import annotations

import sys


def test_operational_diagnostics_report_includes_python() -> None:
    """Happy: operational diagnostics expose a python/runtime field."""
    from mergecraft.enterprise.diagnostics import operational_diagnostics

    report = operational_diagnostics()
    assert report["python"] == sys.version
    assert report["python_version_info"]["major"] == sys.version_info.major
    assert report["python_version_info"]["minor"] == sys.version_info.minor
