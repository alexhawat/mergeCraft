"""Finding lifecycle transition table and ledger enforcement."""

from __future__ import annotations

import pytest

from mergecraft.findings.ledger import FindingLedger
from mergecraft.findings.lifecycle import LifecycleState
from mergecraft.findings.lifecycle_transitions import (
    _ALLOWED_LIFECYCLE_TRANSITIONS,
    assert_lifecycle_transition,
    lifecycle_transition_allowed,
)


@pytest.mark.parametrize("state", list(_ALLOWED_LIFECYCLE_TRANSITIONS))
def test_every_state_has_transition_row(state: LifecycleState) -> None:
    assert state in _ALLOWED_LIFECYCLE_TRANSITIONS


def test_withdrawn_is_terminal() -> None:
    assert lifecycle_transition_allowed("withdrawn", "open") is False
    assert lifecycle_transition_allowed("withdrawn", "withdrawn") is True


def test_ledger_rejects_illegal_transition() -> None:
    book = FindingLedger()
    fp = "abc" * 8
    book.record(fp, "withdrawn", source="verifier-drop", round_index=1)
    with pytest.raises(ValueError, match="illegal lifecycle transition"):
        book.record(fp, "open", source="inline", round_index=2)


def test_assert_transition_accepts_first_record() -> None:
    assert_lifecycle_transition(None, "open")
