"""DG7 feedback capture — accepted / dismissed / disputed with reason (G14).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG7).
Implementation: **DG7.2** — extend ``utils/learnings.py`` with feedback capture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.memory.support import feedback_store_path, sample_fingerprint


@pytest.mark.xfail(reason="green after DG7.2: finding feedback capture", strict=False)
def test_accepted_dismissed_disputed_are_recorded_with_reason(tmp_path: Path) -> None:
    """G14: developer feedback records outcome and reason, not withdrawal alone."""
    from mergecraft.utils.memory import FeedbackOutcome, record_finding_feedback

    repo = tmp_path / "repo"
    repo.mkdir()
    store_path = feedback_store_path(repo)
    fingerprint = sample_fingerprint()

    accepted = record_finding_feedback(
        store_path=store_path,
        fingerprint=fingerprint,
        outcome=FeedbackOutcome.ACCEPTED,
        reason="Valid race — the lock covers the shared map.",
        pr_number=42,
    )
    dismissed = record_finding_feedback(
        store_path=store_path,
        fingerprint=sample_fingerprint(body="SQL injection in test fixture"),
        outcome=FeedbackOutcome.DISMISSED,
        reason="Fixture data is synthetic and never executed.",
        pr_number=42,
    )
    disputed = record_finding_feedback(
        store_path=store_path,
        fingerprint=sample_fingerprint(body="Hard-coded API token"),
        outcome=FeedbackOutcome.DISPUTED,
        reason="Token is a documented sandbox credential.",
        pr_number=43,
    )

    for record in (accepted, dismissed, disputed):
        assert record.reason.strip()
        assert record.outcome in {
            FeedbackOutcome.ACCEPTED,
            FeedbackOutcome.DISMISSED,
            FeedbackOutcome.DISPUTED,
        }

    from mergecraft.utils.memory import load_feedback_store

    store = load_feedback_store(store_path)
    by_outcome = {entry.outcome: entry for entry in store.list_entries()}
    assert by_outcome[FeedbackOutcome.ACCEPTED].reason == accepted.reason
    assert by_outcome[FeedbackOutcome.DISMISSED].reason == dismissed.reason
    assert by_outcome[FeedbackOutcome.DISPUTED].reason == disputed.reason


@pytest.mark.xfail(reason="green after DG7.2: feedback keyed by fingerprint", strict=False)
def test_feedback_is_keyed_by_fingerprint(tmp_path: Path) -> None:
    """Feedback lookups and updates are keyed by finding fingerprint."""
    from mergecraft.utils.memory import (
        FeedbackOutcome,
        get_finding_feedback,
        record_finding_feedback,
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    store_path = feedback_store_path(repo)
    fingerprint = sample_fingerprint()

    record_finding_feedback(
        store_path=store_path,
        fingerprint=fingerprint,
        outcome=FeedbackOutcome.DISMISSED,
        reason="First dismissal reason",
        pr_number=7,
    )
    record_finding_feedback(
        store_path=store_path,
        fingerprint=fingerprint,
        outcome=FeedbackOutcome.ACCEPTED,
        reason="Author fixed the race; finding was valid.",
        pr_number=8,
    )

    latest = get_finding_feedback(store_path=store_path, fingerprint=fingerprint)
    assert latest is not None
    assert latest.fingerprint == fingerprint
    assert latest.outcome == FeedbackOutcome.ACCEPTED
    assert latest.reason == "Author fixed the race; finding was valid."

    other = get_finding_feedback(
        store_path=store_path,
        fingerprint=sample_fingerprint(body="Unrelated finding body"),
    )
    assert other is None
