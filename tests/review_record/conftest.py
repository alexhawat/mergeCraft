"""Shared helpers for wave 12 review-record integrity RED suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import pytest

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.review_taxonomy import FINDING_CATEGORIES

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def require_symbol(module: Any, name: str) -> Any:
    """Return ``module.name`` or fail with a wave-scoped message."""
    obj = getattr(module, name, None)
    if obj is None:
        pytest.fail(f"{module.__name__}.{name} is not defined (plan 12)")
    return obj


def base_finding_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tool": "review-record-fixture",
        "rule_id": "RR-FIXTURE",
        "category": FINDING_CATEGORIES[-1],
        "severity": "Major",
        "confidence": "certain",
        "message": "fixture finding",
        "path": "src/example.py",
        "start_line": 1,
        "end_line": 1,
        "source": "analyzer",
    }
    base.update(overrides)
    return base


def make_test_finding(**overrides: Any) -> Finding:
    return make_finding(**base_finding_kwargs(**overrides))


def finding_scope_field_available() -> bool:
    return "scope" in Finding.model_fields


def make_scoped_finding(
    *,
    scope: Literal["change", "run"],
    severity: str = "Major",
    introduced_by_pr: Literal["true", "false", "unknown"] = "unknown",
    **overrides: Any,
) -> Finding:
    if not finding_scope_field_available():
        pytest.fail("Finding.scope is not defined yet (green after W2)")
    kwargs = base_finding_kwargs(
        severity=severity,
        introduced_by_pr=introduced_by_pr,
        **overrides,
    )
    if scope == "run":
        kwargs["scope"] = "run"
        kwargs["source"] = "trajectory"
        kwargs["introduced_by_pr"] = "false"
        kwargs["path"] = ""
    else:
        kwargs["scope"] = "change"
    if "message" not in overrides:
        rule_id = kwargs.get("rule_id", "RR-FIXTURE")
        if rule_id != "RR-FIXTURE":
            kwargs["message"] = f"fixture finding ({rule_id})"
    return make_finding(**kwargs)


def load_trajectory_fixture(name: str) -> dict[str, Any]:
    path = _FIXTURES / name
    return json.loads(path.read_text(encoding="utf-8"))


def trajectory_record_from_fixture(name: str) -> Any:
    from mergecraft.evidence.trajectory import TrajectoryRecord

    return TrajectoryRecord.model_validate(load_trajectory_fixture(name))
