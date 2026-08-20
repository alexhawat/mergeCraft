"""Shared fixtures for config contract tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _reset_process_tracer_cache() -> Iterator[None]:
    """Reset the process-wide Tracer cache introduced in W4 (#292).

    Tests that create a ``MemorySink`` and call ``run_with_model_chain`` must
    see spans on *their* sink, not on a cached tracer from a sibling test.
    """
    from mergecraft.tracing.tracer import reset_process_tracer_cache

    reset_process_tracer_cache()
    yield
    reset_process_tracer_cache()
