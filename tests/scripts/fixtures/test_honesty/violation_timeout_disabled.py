"""Negative fixture: timeout(0) disables the per-test budget."""

from __future__ import annotations

import pytest


@pytest.mark.timeout(0)
def test_no_per_test_limit() -> None:
    assert True
