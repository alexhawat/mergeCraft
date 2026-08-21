"""Isolate enterprise runtime ContextVar between tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _reset_enterprise_runtime() -> Iterator[None]:
    from mergecraft.enterprise.runtime import reset_enterprise_runtime

    reset_enterprise_runtime()
    yield
    reset_enterprise_runtime()
