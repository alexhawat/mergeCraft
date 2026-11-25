"""Negative fixture: inflated per-test timeout."""

from __future__ import annotations

import pytest


@pytest.mark.timeout(600)
def test_slow_but_rubber_stamped() -> None:
    assert True
