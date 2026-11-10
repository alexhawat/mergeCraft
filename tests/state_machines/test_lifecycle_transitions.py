"""Finding lifecycle transition table and ledger enforcement."""

from __future__ import annotations

from typing import get_args

import pytest

from mergecraft.findings.ledger import FindingLedger
from mergecraft.findings.lifecycle import LifecycleState
from mergecraft.findings.lifecycle_transitions import (
    _ALLOWED_LIFECYCLE_TRANSITIONS,
    assert_lifecycle_transition,
    lifecycle_transition_allowed,
)


@pytest.mark.parametrize("state", get_args(LifecycleState))
def test_every_state_has_transition_row(state: LifecycleState) -> None:
    assert state in _ALLOWED_LIFECYCLE_TRANSITIONS


def test_unpublished_can_be_deferred() -> None:
    assert lifecycle_transition_allowed("unpublished", "deferred")


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


def test_record_if_allowed_keeps_prior_row_on_illegal_transition() -> None:
    book = FindingLedger()
    fp = "def" * 8
    book.record(fp, "withdrawn", source="verifier-drop", round_index=1)
    assert book.record_if_allowed(fp, "open", source="inline", round_index=2) is None
    kept = book.get_record(fp)
    assert kept is not None
    assert kept.state == "withdrawn"
    assert kept.round_index == 1


def test_record_if_allowed_records_legal_transition() -> None:
    book = FindingLedger()
    fp = "fed" * 8
    book.record(fp, "unpublished", source="verification-budget", round_index=1)
    recorded = book.record_if_allowed(fp, "deferred", source="overflow", round_index=1)
    assert recorded is not None
    assert recorded.state == "deferred"
