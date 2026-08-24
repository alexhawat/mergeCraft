"""Shared lazy-import helpers for CB #451 Hunk exporter RED tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from tests.analyzers.support import import_module

_HUNK_EXPORT_MOD = "mergecraft.findings.hunk_export"


def hunk_export_module() -> Any:
    """Return the ``mergecraft.findings.hunk_export`` module."""
    return import_module(_HUNK_EXPORT_MOD)


def require_attr(name: str) -> Any:
    """Return ``hunk_export`` module attribute ``name`` or fail the RED test."""
    mod = hunk_export_module()
    value = getattr(mod, name, None)
    assert value is not None, f"{_HUNK_EXPORT_MOD}.{name} is not implemented"
    return value


def require_callable(name: str) -> Callable[..., Any]:
    """Return a callable exported from ``hunk_export`` or fail the RED test."""
    value = require_attr(name)
    assert callable(value), f"{_HUNK_EXPORT_MOD}.{name} must be callable"
    return value


def sample_line_finding(**overrides: Any) -> Any:
    """Build a line-anchored finding for Hunk export tests."""
    finding_mod = import_module("mergecraft.analyzers.finding")
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
        "remediation": "Remove the unused import.",
        "evidence": ["import os is never referenced"],
    }
    kwargs.update(overrides)
    return finding_mod.make_finding(**kwargs)


def sample_file_level_finding(**overrides: Any) -> Any:
    """Build a file-level finding (``start_line is None``)."""
    return sample_line_finding(start_line=None, end_line=None, **overrides)


def export_hunk_comments(
    findings: list[Any],
    *,
    file_findings: str = "drop",
    first_changed_lines: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Call the exporter under test with the pinned keyword surface."""
    export = require_callable("export_hunk_comments")
    if first_changed_lines is None:
        return export(findings, file_findings=file_findings)
    return export(
        findings,
        file_findings=file_findings,
        first_changed_lines=first_changed_lines,
    )


__all__ = [
    "export_hunk_comments",
    "hunk_export_module",
    "require_attr",
    "require_callable",
    "sample_file_level_finding",
    "sample_line_finding",
]
