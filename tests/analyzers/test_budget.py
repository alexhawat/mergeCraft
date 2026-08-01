"""Inline noise budget (D14)."""

from __future__ import annotations

from mergecraft.review_taxonomy import BODY_ONLY_EFFORT, BODY_ONLY_SEVERITY
from tests.analyzers.support import INLINE_BUDGET, import_module


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


def test_inline_budget_matches_w0_measurement() -> None:
    budget = import_module("mergecraft.analyzers.budget")
    assert budget.default_inline_budget() == INLINE_BUDGET


def test_overflow_lands_in_mechanical_section() -> None:
    budget = import_module("mergecraft.analyzers.budget")
    findings = [_finding("Major", path=f"src/f{i}.py", line=i) for i in range(1, INLINE_BUDGET + 4)]
    placement = budget.place_findings(findings, inline_budget=INLINE_BUDGET)
    assert len(placement.inline) <= INLINE_BUDGET
    assert placement.mechanical_section is not None
    assert "### 🔧 Mechanical findings" in placement.mechanical_section


def test_trivial_severity_never_inline() -> None:
    budget = import_module("mergecraft.analyzers.budget")
    trivial = _finding(BODY_ONLY_SEVERITY)
    placement = budget.place_findings([trivial], inline_budget=INLINE_BUDGET)
    assert trivial not in placement.inline
    assert BODY_ONLY_SEVERITY not in {f.severity for f in placement.inline}


def test_low_value_effort_never_inline() -> None:
    budget = import_module("mergecraft.analyzers.budget")
    placement = budget.place_findings(
        [],
        inline_budget=INLINE_BUDGET,
        agent_findings=[{"severity": "Minor", "effort": BODY_ONLY_EFFORT, "path": "src/x.py"}],
    )
    assert not any(row.get("effort") == BODY_ONLY_EFFORT for row in placement.inline)


def test_agent_findings_win_ties_over_analyzer() -> None:
    budget = import_module("mergecraft.analyzers.budget")
    agent = _finding("Major", source="agent", path="src/tie.py", line=10)
    analyzer = _finding("Major", source="analyzer", path="src/tie.py", line=10)
    at_cap = [_finding("Major", path=f"src/other{i}.py", line=i) for i in range(1, INLINE_BUDGET)]
    placement = budget.place_findings([*at_cap, agent, analyzer], inline_budget=INLINE_BUDGET)
    inline_sources = {f.source for f in placement.inline if f.path == "src/tie.py"}
    assert "agent" in inline_sources
    assert "analyzer" not in inline_sources or len(placement.mechanical) >= 1
