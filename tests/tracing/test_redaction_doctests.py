"""BR1.1 / BR2 — execute ``mergecraft.tracing.redaction`` doctests (D3)."""

from __future__ import annotations

import doctest


def test_module_doctests_pass() -> None:
    """D3: module docstring examples are executable regression tests."""
    import mergecraft.tracing.redaction as module

    failures, _attempted = doctest.testmod(module, verbose=False)
    assert failures == 0
