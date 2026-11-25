"""Negative fixture: flaky marker."""

from __future__ import annotations

import pytest


@pytest.mark.flaky(reruns=3)
def test_unstable() -> None:
    assert True
