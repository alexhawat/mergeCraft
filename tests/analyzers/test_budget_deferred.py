"""Deferred findings placement (RC1, D1, D14) — W1 RED suite."""

from __future__ import annotations

from dataclasses import fields
from typing import Any

from mergecraft.review_taxonomy import BODY_ONLY_EFFORT, BODY_ONLY_SEVERITY
from tests.analyzers.support import INLINE_BUDGET, import_module

DEFERRED_SECTION_HEADING = "### 🗂 Deferred findings"


def _finding(
    severity: str, source: str = "analyzer", path: str = "src/a.py", line: int = 1
) -> object:
    finding_mod = import_module("mergecraft.analyzers.finding")
    return finding_mod.make_finding(
        tool="actionlint",
        rule_id="rule",
        category="Maintainability & Code Quality",
        severity=severity,
        confidence="likely",
        message=f"finding at {path}:{line}",
        path=path,
        start_line=line,
        end_line=line,
        source=source,
    )


def _agent_overflow(
    *,
    overflow_count: int = 1,
    overflow_body: str = "Race when two workers claim the same row",
    overflow_path: str = "src/overflow.py",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "severity": "Major",
            "path": f"src/inline{i:02d}.py",
            "line": i,
            "body": f"inline filler {i}",
        }
        for i in range(1, INLINE_BUDGET + 1)
    ]
    for index in range(overflow_count):
        rows.append(
            {
                "severity": "Major",
                "path": overflow_path if index == 0 else f"src/overflow{index:02d}.py",
                "line": INLINE_BUDGET + index + 1,
                "body": overflow_body if index == 0 else f"{overflow_body} ({index})",
            }
        )
    return rows


def test_overflowed_agent_finding_keeps_its_body() -> None:
    """RC1: agent overflow retains reasoning in the deferred lane, not a bodyless stub."""
    budget = import_module("mergecraft.analyzers.budget")
    overflow_body = "Race when two workers claim the same row"
    placement = budget.place_findings(
        [],
        inline_budget=INLINE_BUDGET,
        agent_findings=_agent_overflow(overflow_body=overflow_body),
    )
    deferred_section = getattr(placement, "deferred_section", None)
    assert deferred_section is not None, "agent overflow must render a deferred section"
    assert overflow_body in deferred_section
    mechanical = placement.mechanical_section or ""
    assert overflow_body not in mechanical


def test_deferred_section_renders_severity_path_and_body() -> None:
    budget = import_module("mergecraft.analyzers.budget")
    overflow_body = "Missing rollback when the write fails mid-batch"
    overflow_path = "src/zz-batch.py"
    placement = budget.place_findings(
        [],
        inline_budget=INLINE_BUDGET,
        agent_findings=_agent_overflow(
            overflow_body=overflow_body,
            overflow_path=overflow_path,
        ),
    )
    deferred_section = getattr(placement, "deferred_section", None)
    assert deferred_section is not None
    assert DEFERRED_SECTION_HEADING in deferred_section
    assert "Major" in deferred_section
    assert overflow_path in deferred_section
    assert overflow_body in deferred_section


def test_analyzer_overflow_still_renders_as_a_compact_tool_table() -> None:
    """Analyzer overflow stays in the mechanical table; agent overflow must not."""
    budget = import_module("mergecraft.analyzers.budget")
    analyzer_findings = [
        _finding("Major", path=f"src/analyzer{i:02d}.py", line=i)
        for i in range(1, INLINE_BUDGET + 3)
    ]
    placement = budget.place_findings(
        analyzer_findings,
        inline_budget=INLINE_BUDGET,
        agent_findings=_agent_overflow(),
    )
    mechanical = placement.mechanical_section
    assert mechanical is not None
    assert "| Tool | Findings |" in mechanical
    assert "### 🔧 Mechanical findings" in mechanical
    mechanical_sources = {finding.source for finding in placement.mechanical}
    assert "agent" not in mechanical_sources
    deferred_section = getattr(placement, "deferred_section", None)
    assert deferred_section is not None


def test_inline_budget_is_still_eight() -> None:
    """D1 invariant: inline cap stays 8 for this program."""
    budget = import_module("mergecraft.analyzers.budget")
    assert budget.default_inline_budget() == 8
    assert INLINE_BUDGET == 8


def test_trivial_and_low_value_never_reach_the_deferred_section() -> None:
    """Trivial / Low value belong in Nitpicks, not the deferred lane (REVIEW-CHECKS §5)."""
    budget = import_module("mergecraft.analyzers.budget")
    placement = budget.place_findings(
        [],
        inline_budget=INLINE_BUDGET,
        agent_findings=[
            {
                "severity": BODY_ONLY_SEVERITY,
                "path": "src/nit.py",
                "line": 1,
                "body": "nitpick body",
            },
            {
                "severity": "Minor",
                "effort": BODY_ONLY_EFFORT,
                "path": "src/low.py",
                "line": 2,
                "body": "low-value body",
            },
            {
                "severity": "Major",
                "path": "src/real.py",
                "line": 3,
                "body": "real anchored finding",
            },
        ],
    )
    field_names = {field.name for field in fields(budget.FindingPlacement)}
    assert "deferred" in field_names
    deferred = getattr(placement, "deferred", [])
    assert deferred == []
    deferred_section = getattr(placement, "deferred_section", None)
    assert deferred_section is None
