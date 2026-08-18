"""Shared helpers for findings precision tests (DG1.1 RED)."""

from __future__ import annotations

from typing import Any

from tests.analyzers.support import import_module


def make_finding(
    *,
    tool: str = "agent",
    rule_id: str = "agent:1",
    category: str = "Functional Correctness",
    severity: str = "Major",
    confidence: str = "likely",
    message: str = "defect",
    path: str = "src/app.py",
    start_line: int = 10,
    end_line: int = 10,
    source: str = "agent",
    introduced_by_pr: str = "true",
    fingerprint: str | None = None,
    **extra: Any,
) -> Any:
    """Build a taxonomy-valid ``Finding`` for DG1 contract tests."""
    finding_mod = import_module("mergecraft.analyzers.finding")
    body: dict[str, Any] = {
        "tool": tool,
        "rule_id": rule_id,
        "category": category,
        "severity": severity,
        "confidence": confidence,
        "message": message,
        "path": path,
        "start_line": start_line,
        "end_line": end_line,
        "source": source,
        "introduced_by_pr": introduced_by_pr,
    }
    if fingerprint is not None:
        body["fingerprint"] = fingerprint
    body.update(extra)
    return finding_mod.make_finding(**body)
