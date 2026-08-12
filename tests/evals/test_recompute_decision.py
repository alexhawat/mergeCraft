"""Packet-backed replay — the link that makes a promoted case a real test (C7).

Before this, ``replay_case`` could only compare against a verdict an operator
typed in, so a promoted test asserted nothing in CI. These tests pin that a case
carrying its recorded evidence is re-decided by the *current* gate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mergecraft.evals.store import (
    CASE_STATUS_BLOCKED,
    CASE_STATUS_PASSED,
    CASE_STATUS_REGRESSION,
    Case,
    recompute_decision,
    render_case_text,
    replay_case,
)
from mergecraft.utils.learnings import LearningProvenance


def _finding(severity: str = "Critical") -> dict[str, Any]:
    return {
        "path": "src/a.py",
        "start_line": 1,
        "end_line": 2,
        "message": "boom",
        "severity": severity,
        "confidence": "certain",
        "category": "Functional Correctness",
        "source": "agent",
        "fingerprint": "abc123",
        "tool": "agent",
        "rule_id": "agent:1",
        "introduced_by_pr": "true",
        "evidence": ["x"],
        "remediation": "fix it",
        "autofix": None,
        "cluster_id": None,
    }


def _case(
    *,
    expected: str = "failure",
    findings: list[dict[str, Any]] | None = None,
    run_succeeded: bool = True,
    trust_tier: str = "trusted",
) -> Case:
    when = datetime(2026, 8, 10, tzinfo=UTC)
    return Case(
        id="case-001",
        title="t",
        category="missed_finding",
        submitted_at=when,
        run_id="run-1",
        pr_number=1,
        failure_mode="wrong_decision",
        expected_finding="Critical in src/a.py",
        expected_decision=expected,
        replay_command="mergecraft eval replay case-001",
        provenance=LearningProvenance(
            run_id="run-1",
            pr_number=1,
            source_field="eval_bank",
            author_login="alexhawat",
            author_association="OWNER",
            trust_tier="trusted",
            timestamp=when,
        ),
        body="",
        recorded_findings=findings,
        run_succeeded=run_succeeded,
        trust_tier=trust_tier,
    )


def test_a_blocker_is_recomputed_without_an_operator() -> None:
    assert recompute_decision(_case(findings=[_finding()])) == "failure"


def test_a_case_without_evidence_cannot_be_decided() -> None:
    """Legacy cases keep their old behaviour rather than guessing a verdict."""
    assert recompute_decision(_case(findings=None)) is None
    assert _case(findings=None).is_replayable is False


def test_replay_uses_recorded_evidence_when_no_verdict_is_supplied() -> None:
    """The whole point: a promoted test detects drift in CI, unaided."""
    diff = replay_case(_case(findings=[_finding()]), current_decision=None)

    assert diff.current_decision == "failure"
    assert diff.status == CASE_STATUS_PASSED


def test_replay_reports_a_regression_when_the_gate_drifts() -> None:
    # The case expects `success`; the gate blocks on a Critical finding.
    diff = replay_case(_case(expected="success", findings=[_finding()]), current_decision=None)

    assert diff.status == CASE_STATUS_REGRESSION


def test_evidenceless_case_still_lands_blocked() -> None:
    diff = replay_case(_case(findings=None), current_decision=None)

    assert diff.status == CASE_STATUS_BLOCKED


def test_an_explicit_verdict_outranks_the_recomputed_one() -> None:
    """An operator must be able to contradict stored evidence."""
    diff = replay_case(_case(findings=[_finding()]), current_decision="success")

    assert diff.current_decision == "success"
    assert diff.status == CASE_STATUS_REGRESSION


def test_a_crashed_run_is_never_permissive() -> None:
    assert recompute_decision(_case(findings=[], run_succeeded=False)) == "neutral"


def test_an_untrusted_run_is_never_permissive() -> None:
    assert recompute_decision(_case(findings=[], trust_tier="untrusted")) == "neutral"


def test_unparsable_evidence_reports_cannot_decide_not_a_verdict() -> None:
    """A schema change that invalidates stored evidence must surface, not guess."""
    assert recompute_decision(_case(findings=[{"nonsense": True}])) is None


def test_recorded_evidence_round_trips_through_the_case_file() -> None:
    text = render_case_text(_case(findings=[_finding()]))

    assert "recorded_findings" in text
    assert "run_succeeded" in text
