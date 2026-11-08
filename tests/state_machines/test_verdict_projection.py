"""Composed verdict projection stays monotone."""

from __future__ import annotations

from mergecraft.agents.gates import decide_approval
from mergecraft.analyzers.finding import make_finding
from mergecraft.verdicts.projection import project_run_verdict, project_structural_conclusion
from mergecraft.run_outcome import RunOutcome


def _critical():
    return make_finding(
        tool="agent",
        rule_id="R",
        category="Security & Privacy",
        severity="Critical",
        confidence="certain",
        message="blocker",
        path="a.py",
        start_line=1,
        end_line=1,
        source="agent",
        fingerprint="fp-critical",
    )


def test_structural_matches_decide_approval_list() -> None:
    findings = [_critical()]
    direct = decide_approval(findings, run_succeeded=True, tier="trusted")
    projected = project_structural_conclusion(findings, run_succeeded=True, tier="trusted")
    assert direct == projected == "failure"


def test_failed_run_neutral_even_without_blockers() -> None:
    composed = project_run_verdict([], outcome=RunOutcome.failed, tier="trusted")
    assert composed.structural == "neutral"
    assert composed.run_succeeded is False
