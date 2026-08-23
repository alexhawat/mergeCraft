"""Shared lazy-import helpers for CA #452 short finding id RED tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tests.analyzers.support import import_module

_FINDING_MOD = "mergecraft.analyzers.finding"


def finding_module() -> Any:
    """Return the ``mergecraft.analyzers.finding`` module."""
    return import_module(_FINDING_MOD)


def require_attr(name: str) -> Any:
    """Return ``finding`` module attribute ``name`` or fail the RED test."""
    mod = finding_module()
    value = getattr(mod, name, None)
    assert value is not None, f"{_FINDING_MOD}.{name} is not implemented"
    return value


def require_callable(name: str) -> Callable[..., Any]:
    """Return a callable exported from ``finding`` or fail the RED test."""
    value = require_attr(name)
    assert callable(value), f"{_FINDING_MOD}.{name} must be callable"
    return value


def sample_finding(*, fingerprint: str | None = None) -> Any:
    """Build a taxonomy-valid finding for output-surface tests."""
    kwargs: dict[str, Any] = {
        "tool": "ruff",
        "rule_id": "F401",
        "category": "Maintainability & Code Quality",
        "severity": "Minor",
        "confidence": "likely",
        "message": "unused import os",
        "path": "src/demo.py",
        "start_line": 3,
        "end_line": 3,
        "source": "analyzer",
    }
    if fingerprint is not None:
        kwargs["fingerprint"] = fingerprint
    return finding_module().make_finding(**kwargs)


def collision_fingerprints() -> tuple[str, str]:
    """Two distinct 24-char fingerprints that share the same 6-char truncation."""
    prefix = "a83f91"
    return (
        f"{prefix}{'0' * 18}",
        f"{prefix}{'1' * 18}",
    )


__all__ = [
    "collision_fingerprints",
    "finding_module",
    "require_attr",
    "require_callable",
    "sample_finding",
]
