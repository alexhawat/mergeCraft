"""Inline comment bodies include stable short finding ids."""

from __future__ import annotations

from tests.analyzers.support import import_module

from mergecraft.mcp.review import format_analyzer_inline_body


def test_format_analyzer_inline_body_includes_short_id() -> None:
    finding_mod = import_module("mergecraft.analyzers.finding")
    finding = finding_mod.make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="unused import",
        path="demo.py",
        start_line=1,
        end_line=1,
        source="analyzer",
    )
    short_id = finding_mod.finding_short_id(finding.fingerprint)
    body = format_analyzer_inline_body(finding, short_id=short_id)
    assert short_id in body
    assert finding.message in body
