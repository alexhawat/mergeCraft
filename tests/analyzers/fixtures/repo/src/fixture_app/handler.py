"""Planted Python issues for C1 language gates."""

from __future__ import annotations


def greet(name: str) -> str:
    # Planted: real type error for mypy/pyright (catalog C1)
    return name + 42


def unused_helper() -> None:
    # Planted: ruff F841 when enabled (--ignore-noqa in catalog adapter)
    stale = "never read"  # noqa: F841
