"""Negative fixture: silent exception swallowing."""

from __future__ import annotations


def test_swallows() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        pass
