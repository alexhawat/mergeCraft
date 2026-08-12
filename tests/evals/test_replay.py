"""Pure-function tests for the replay diff (W11.4).

The replay function is pure: it takes a case and a current verdict,
and returns a structured :class:`ReplayDiff`. The state transitions
are the only thing the test suite pins — the actual replay engine is
the CLI's responsibility (the CLI asks the caller for the current
verdict; the function deterministically compares it).

These tests prove the diff is deterministic and that the three
statuses (passed / regression / blocked) cover every legitimate case.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mergecraft.evals.store import (
    CASE_STATUS_BLOCKED,
    CASE_STATUS_PASSED,
    CASE_STATUS_REGRESSION,
    Case,
    replay_case,
)
from mergecraft.utils.learnings import LearningProvenance


def _provenance() -> LearningProvenance:
    return LearningProvenance(
        run_id="synthetic",
        pr_number=1,
        source_field="eval_bank",
        author_login="synthetic",
        author_association="OWNER",
        trust_tier="trusted",
        timestamp=datetime(2026, 8, 9, 10, 0, 0, tzinfo=UTC),
    )


def _case(expected_decision: str = "block") -> Case:
    return Case(
        id="synthetic-001",
        title="missed finding",
        category="missed_finding",
        submitted_at=datetime(2026, 8, 9, 10, 0, 0, tzinfo=UTC),
        run_id="synthetic",
        pr_number=1,
        failure_mode="missed_finding",
        expected_finding="src/mergecraft/foo.py:42",
        expected_decision=expected_decision,
        replay_command="mergecraft eval replay synthetic-001",
        provenance=_provenance(),
        body="",
    )


# ── pass / regression / blocked ────────────────────────────────────────


def test_replay_passes_when_verdicts_match() -> None:
    """``replay_case`` returns ``passed`` when the verdicts agree."""
    diff = replay_case(_case(expected_decision="block"), current_decision="block")
    assert diff.status == CASE_STATUS_PASSED
    assert diff.case_id == "synthetic-001"
    assert diff.expected_decision == "block"
    assert diff.current_decision == "block"


def test_replay_reports_regression_when_verdicts_differ() -> None:
    """``replay_case`` returns ``regression`` when the verdicts disagree."""
    diff = replay_case(
        _case(expected_decision="block"),
        current_decision="auto_merge",
    )
    assert diff.status == CASE_STATUS_REGRESSION
    assert diff.current_decision == "auto_merge"
    assert diff.expected_decision == "block"
    assert "expected" in diff.notes
    assert "auto_merge" in diff.notes


def test_replay_reports_blocked_when_current_is_none() -> None:
    """``replay_case`` returns ``blocked`` when no current verdict was given."""
    diff = replay_case(_case(), current_decision=None)
    assert diff.status == CASE_STATUS_BLOCKED
    assert diff.current_decision is None
    assert diff.expected_decision == "block"
    assert "replay engine" in diff.notes


# ── per-verdict matrix ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("expected", "current", "expected_status"),
    [
        ("block", "block", CASE_STATUS_PASSED),
        ("block", "request_changes", CASE_STATUS_REGRESSION),
        ("auto_merge", "auto_merge", CASE_STATUS_PASSED),
        ("auto_merge", "block", CASE_STATUS_REGRESSION),
        ("request_changes", "auto_merge", CASE_STATUS_REGRESSION),
        ("neutral", "neutral", CASE_STATUS_PASSED),
        ("require_human_review", "require_human_review", CASE_STATUS_PASSED),
        ("unavailable", "auto_merge", CASE_STATUS_REGRESSION),
    ],
)
def test_replay_matrix(expected: str, current: str, expected_status: str) -> None:
    """The replay diff is deterministic across the verdict vocabulary."""
    diff = replay_case(_case(expected_decision=expected), current_decision=current)
    assert diff.status == expected_status
    assert diff.expected_decision == expected
    assert diff.current_decision == current


# ── determinism ────────────────────────────────────────────────────────


def test_replay_is_deterministic() -> None:
    """The same inputs produce the same output (no hidden state)."""
    case = _case()
    a = replay_case(case, current_decision="block")
    b = replay_case(case, current_decision="block")
    assert a == b


def test_replay_does_not_mutate_case() -> None:
    """The replay function is pure — the case is unchanged after the call."""
    case = _case()
    snapshot = case.model_dump()
    replay_case(case, current_decision="auto_merge")
    assert case.model_dump() == snapshot


# ── shape ──────────────────────────────────────────────────────────────


def test_replay_diff_is_serializable_to_json() -> None:
    """The diff can be serialized to JSON (it is the wire shape)."""
    diff = replay_case(_case(), current_decision="block")
    as_json = diff.model_dump_json()
    assert "synthetic-001" in as_json
    assert "passed" in as_json


def test_replay_case_id_propagated() -> None:
    """The case id is propagated to the diff."""
    case = _case()
    case = case.model_copy(update={"id": "synthetic-007"})
    diff = replay_case(case, current_decision="block")
    assert diff.case_id == "synthetic-007"
