"""Test-only helpers (importable from meat_python_plus/tests)."""

from __future__ import annotations

import importlib
from typing import Any

import pytest


def import_or_fail(module: str) -> Any:
    """Import a W2+ module; fail the test if it is not implemented yet."""
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        pytest.fail(f"module {module!r} is not implemented yet: {exc}")


def require_attr(module: Any, name: str) -> Any:
    if not hasattr(module, name):
        pytest.fail(f"{module.__name__}.{name} is not implemented yet")
    return getattr(module, name)
