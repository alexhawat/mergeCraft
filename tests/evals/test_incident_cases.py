"""Incident-derived eval cases (#1163)."""

from __future__ import annotations

from pathlib import Path

from mergecraft.evals.incident import IncidentCaseInput, add_incident_case
from mergecraft.evals.store import CATEGORY_INCIDENT_DERIVED, load_case


def test_incident_case_refused_without_provenance(tmp_path: Path) -> None:
    spec = IncidentCaseInput(
        case_id="incident-test-001",
        title="test",
        incident_pr=1,
        followup_pr=2,
        confirmed_bug_path="src/x.py",
        confirmed_bug_start_line=1,
        confirmed_bug_end_line=3,
        label_provenance="not-a-real-tier",
        run_id="run",
        author_login="alice",
    )
    outcome = add_incident_case(spec, bank_dir=tmp_path)
    assert not outcome.accepted
    assert "provenance" in outcome.reason.casefold()


def test_incident_case_writes_agent_seeded(tmp_path: Path) -> None:
    spec = IncidentCaseInput(
        case_id="incident-test-002",
        title="bad deploy",
        incident_pr=10,
        followup_pr=11,
        confirmed_bug_path="app/main.py",
        confirmed_bug_start_line=4,
        confirmed_bug_end_line=8,
        label_provenance="agent-seeded",
        run_id="run-1",
        author_login="alice",
    )
    outcome = add_incident_case(spec, bank_dir=tmp_path)
    assert outcome.accepted
    case = load_case(Path(outcome.path))
    assert case.category == CATEGORY_INCIDENT_DERIVED
    assert case.incident_pr == 10
    assert case.followup_pr == 11
    assert case.expected_finding == "app/main.py:4-8"
