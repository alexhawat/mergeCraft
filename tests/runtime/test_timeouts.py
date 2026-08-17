"""CC3 — bounded external-operation timeouts (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Authoring wave: **CC3.1** (RED). Implementation: **CC3.2**.
"""

from __future__ import annotations

from mergecraft.utils.run_bounds import (
    EXTERNAL_OPERATION_TIMEOUTS,
    enumerate_unbounded_external_operations,
    resolve_run_bounds,
    timeout_for_external_operation,
)


def test_every_external_operation_has_a_timeout() -> None:
    """Every registered external operation has a positive finite timeout."""
    unbounded = enumerate_unbounded_external_operations()
    assert not unbounded, f"unbounded external operations: {unbounded}"
    for name, seconds in EXTERNAL_OPERATION_TIMEOUTS.items():
        assert isinstance(name, str)
        assert name
        assert isinstance(seconds, (int, float))
        assert seconds > 0, f"{name!r} timeout must be positive, got {seconds!r}"


def test_context_retrieval_timeout_is_bounded() -> None:
    """Context retrieval uses a dedicated bounded timeout from ``RunBounds``."""
    bounds = resolve_run_bounds(env={})
    assert bounds.context_retrieval_timeout_s > 0
    retrieval = timeout_for_external_operation("context_retrieval", bounds=bounds)
    assert retrieval == bounds.context_retrieval_timeout_s
    assert retrieval <= bounds.external_operation_timeout_s
