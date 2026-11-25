"""Negative fixture: constant sleep in a test body."""

from __future__ import annotations

import time


def test_waits_fixed() -> None:
    time.sleep(0.5)
    assert True
