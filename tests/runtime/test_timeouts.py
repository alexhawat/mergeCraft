"""CC3 — bounded external-operation timeouts (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Authoring wave: **CC3.1** (RED). Implementation: **CC3.2**.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

_CC3_2_XFAIL = pytest.mark.xfail(
    reason="green after CC3.2: external operation timeouts",
    strict=False,
)


def _run_bounds() -> Any:
    try:
        return importlib.import_module("mergecraft.utils.run_bounds")
    except ImportError as exc:
        pytest.fail(f"mergecraft.utils.run_bounds not importable: {exc}")


@_CC3_2_XFAIL
def test_every_external_operation_has_a_timeout() -> None:
    """Every registered external operation has a positive finite timeout."""
    mod = _run_bounds()
    unbounded = mod.enumerate_unbounded_external_operations()
    assert not unbounded, f"unbounded external operations: {unbounded}"
    for name, seconds in mod.EXTERNAL_OPERATION_TIMEOUTS.items():
        assert isinstance(name, str)
        assert name
        assert isinstance(seconds, (int, float))
        assert seconds > 0, f"{name!r} timeout must be positive, got {seconds!r}"


@_CC3_2_XFAIL
def test_context_retrieval_timeout_is_bounded() -> None:
    """Context retrieval uses a dedicated bounded timeout from ``RunBounds``."""
    mod = _run_bounds()
    bounds = mod.resolve_run_bounds(env={})
    assert bounds.context_retrieval_timeout_s > 0
    retrieval = mod.timeout_for_external_operation("context_retrieval", bounds=bounds)
    assert retrieval == bounds.context_retrieval_timeout_s
    assert retrieval <= bounds.external_operation_timeout_s
