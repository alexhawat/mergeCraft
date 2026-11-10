"""Terminal publication state machine — total mapping, no contradictory combos."""

from __future__ import annotations

from mergecraft.agents.shared import AgentResult
from mergecraft.mcp.tool_state import ReviewRecord, TerminalSubmission, init_tool_state
from mergecraft.review.terminal_publication import (
    TerminalPublicationState,
    apply_terminal_publication_flags,
    resolve_terminal_publication,
)


def _state(**kwargs: object):
    ts = init_tool_state(owner="o", name="n", dir="/tmp/x")
    for key, val in kwargs.items():
        setattr(ts, key, val)
    return ts


def test_apply_flags_are_mutually_exclusive() -> None:
    ts = _state()
    apply_terminal_publication_flags(ts, TerminalPublicationState.publish_failed)
    assert ts.terminal_publication_failed is True
    assert ts.terminal_publication_mismatch is False
    apply_terminal_publication_flags(ts, TerminalPublicationState.verdict_mismatch)
    assert ts.terminal_publication_failed is False
    assert ts.terminal_publication_mismatch is True


def test_sticky_only_is_not_applicable_for_receipt() -> None:
    ts = _state(review_publication_sticky_only=True)
    res = resolve_terminal_publication(
        ts,
        result=AgentResult(success=True, terminal_submission_received=True),
        verdict_protocol="enforce",
        mode="Review",
    )
    assert res.state is TerminalPublicationState.sticky_progress_only
    assert res.terminal_publication_receipt is None


def test_failed_publication_has_no_receipt() -> None:
    ts = _state(terminal_publication_failed=True)
    ts.terminal_submission = TerminalSubmission(
        id="x",
        verdict="approve",
        summary="s",
        findings=[],
        payload_hash="h",
        submitted_at="t",
        attempt_id=0,
    )
    res = resolve_terminal_publication(
        ts,
        result=AgentResult(success=True, terminal_submission_received=True),
        verdict_protocol="enforce",
        mode="Review",
    )
    assert res.state is TerminalPublicationState.publish_failed
    assert res.terminal_publication_failed is True
    assert res.terminal_publication_receipt is False


def test_published_ok_requires_verdict_on_receipt() -> None:
    ts = _state()
    ts.review = ReviewRecord(id=1, node_id="n", reviewed_sha="abc", verdict="approve")
    ts.terminal_submission = TerminalSubmission(
        id="x",
        verdict="approve",
        summary="s",
        findings=[],
        payload_hash="h",
        submitted_at="t",
        attempt_id=0,
    )
    res = resolve_terminal_publication(
        ts,
        result=AgentResult(success=True, terminal_submission_received=True),
        verdict_protocol="enforce",
        mode="Review",
    )
    assert res.state is TerminalPublicationState.published_ok
    assert res.terminal_publication_receipt is True
