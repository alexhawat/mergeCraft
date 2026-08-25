"""Shared fixtures for CE #455 per-lens routing capability RED tests (D6)."""

from __future__ import annotations

from typing import Any

from tests.analyzers.support import import_module

_LENS_CAPABILITY_MOD = "mergecraft.evals.lens_capability"


def lens_capability_module() -> Any:
    """Return the ``mergecraft.evals.lens_capability`` module."""
    return import_module(_LENS_CAPABILITY_MOD)


def require_attr(name: str) -> Any:
    """Return a symbol from ``mergecraft.evals.lens_capability`` or fail the RED test."""
    mod = lens_capability_module()
    value = getattr(mod, name, None)
    assert value is not None, f"{_LENS_CAPABILITY_MOD}.{name} is not implemented"
    return value


def require_callable(name: str) -> Any:
    """Return a callable from ``mergecraft.evals.lens_capability`` or fail the RED test."""
    value = require_attr(name)
    assert callable(value), f"{_LENS_CAPABILITY_MOD}.{name} must be callable"
    return value


def routing_label(case_id: str, *expected_lens_ids: str) -> Any:
    """Build one labeled routing case (ground-truth lenses that should fire)."""
    label_cls = require_attr("LensRoutingCaseLabel")
    return label_cls(case_id=case_id, expected_lens_ids=tuple(expected_lens_ids))


def routing_outcome(case_id: str, *selected_lens_ids: str) -> Any:
    """Build one observed routing outcome (lenses the router actually selected)."""
    outcome_cls = require_attr("LensRoutingCaseOutcome")
    return outcome_cls(case_id=case_id, selected_lens_ids=tuple(selected_lens_ids))


__all__ = [
    "lens_capability_module",
    "require_attr",
    "require_callable",
    "routing_label",
    "routing_outcome",
]
