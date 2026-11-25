"""Negative fixture: contextlib.suppress masks failures."""

from __future__ import annotations

import contextlib


def test_masks() -> None:
    with contextlib.suppress(ValueError):
        raise ValueError("boom")
    assert True
