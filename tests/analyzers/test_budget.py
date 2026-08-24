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


def test_mechanical_section_includes_short_ids() -> None:
    """Production markdown surfaces batch-resolved short ids for overflow findings."""
    finding_mod = import_module("mergecraft.analyzers.finding")
    budget = import_module("mergecraft.analyzers.budget")
    findings = [_finding("Major", path=f"src/f{i}.py", line=i) for i in range(1, INLINE_BUDGET + 2)]
    placement = budget.place_findings(findings, inline_budget=0)
    assert placement.mechanical_section is not None
    overflow = findings[0]
    short_id = finding_mod.finding_short_id(overflow.fingerprint)
    assert short_id in placement.mechanical_section


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


def test_overflow_agent_findings_get_distinct_fingerprints() -> None:
    """Overflowed agent findings must stay individually identifiable (C5)."""
    budget = import_module("mergecraft.analyzers.budget")
    taxonomy = import_module("mergecraft.review_taxonomy")
    agent_findings = [
        {
            "severity": "Major",
            "path": f"src/agent{i:02d}.py",
            "line": i,
            "body": f"agent finding number {i}",
        }
        for i in range(1, INLINE_BUDGET + 4)
    ]
    placement = budget.place_findings(
        [], inline_budget=INLINE_BUDGET, agent_findings=agent_findings
    )
    overflow = [f for f in placement.deferred if f.source == "agent"]
    assert len(overflow) == 3
    fingerprints = [f.fingerprint for f in overflow]
    assert len(set(fingerprints)) == len(fingerprints)
    assert "agent-inline" not in fingerprints
    by_path = {str(row["path"]): str(row["body"]) for row in agent_findings}
    for finding in overflow:
        assert finding.fingerprint == taxonomy.finding_fingerprint(
            path=finding.path, body=by_path[finding.path]
        )


def test_overflow_agent_finding_keeps_supplied_fingerprint() -> None:
    budget = import_module("mergecraft.analyzers.budget")
    agent_findings: list[dict[str, object]] = [
        {"severity": "Major", "path": f"src/a{i:02d}.py", "line": i, "body": f"filler {i}"}
        for i in range(1, INLINE_BUDGET + 1)
    ]
    agent_findings.append(
        {
            "severity": "Major",
            "path": "src/zz-last.py",
            "line": 3,
            "body": "already stamped",
            "fingerprint": "deadbeefcafe",
        }
    )
    placement = budget.place_findings(
        [], inline_budget=INLINE_BUDGET, agent_findings=agent_findings
    )
    overflow = [f for f in placement.deferred if f.source == "agent"]
    assert [f.fingerprint for f in overflow] == ["deadbeefcafe"]


def test_agent_findings_win_ties_over_analyzer() -> None:
    budget = import_module("mergecraft.analyzers.budget")
    agent = _finding("Major", source="agent", path="src/tie.py", line=10)
    analyzer = _finding("Major", source="analyzer", path="src/tie.py", line=10)
    at_cap = [_finding("Major", path=f"src/other{i}.py", line=i) for i in range(1, INLINE_BUDGET)]
    placement = budget.place_findings([*at_cap, agent, analyzer], inline_budget=INLINE_BUDGET)
    inline_sources = {f.source for f in placement.inline if f.path == "src/tie.py"}
    assert "agent" in inline_sources
    assert "analyzer" not in inline_sources or len(placement.mechanical) >= 1
