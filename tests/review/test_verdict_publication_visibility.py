"""A recorded verdict that reaches no review must say why (#1017).

PR #1017's Codex rung recorded ``request_changes`` and published no review. The
only visible trace was the failing ``mergecraft-approval`` check:
``_publish_recorded_verdict`` returned early and recorded nothing, so the evidence
packet could not distinguish "this run published nothing" from "this run never
tried". These tests pin the reasons apart — and pin that the reason reaches the
run's trajectory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.agents.shared import AgentResult
from mergecraft.mcp.verdict import submit_review_verdict_tool
from tests.review_record.test_w15_deterministic_record import _context, _Scm

if TYPE_CHECKING:
    from pathlib import Path

_SUBMISSION = {
    "verdict": "request_changes",
    "summary": "Blocking.",
    "findings": [
        {"path": "a.py", "line": 1, "severity": "Major", "body": "Blocking finding for the test."}
    ],
}


async def _state_with_a_recorded_verdict(tmp_path: Path) -> Any:
    """A run that recorded a terminal verdict and never called ``select_mode``."""
    ctx = _context(tmp_path, _Scm())
    assert ctx.tool_state.selected_mode is None

    result = await submit_review_verdict_tool(ctx).execute(dict(_SUBMISSION))

    assert result.is_error is False
    assert ctx.tool_state.terminal_submission is not None
    return ctx


def test_a_received_submission_publishes() -> None:
    from mergecraft.main import owes_a_terminal_review, publication_skip_reason

    class _State:
        terminal_submission = object()
        selected_mode = "Review"

    assert owes_a_terminal_review(_State())  # type: ignore[arg-type]
    reason = publication_skip_reason(
        _State(),  # type: ignore[arg-type]
        AgentResult(success=True, terminal_submission_received=True),
        verdict_protocol="enforce",
    )

    assert reason is None


def test_a_run_that_recorded_nothing_owes_a_review() -> None:
    """Nothing owed. The caller returns before any reason is computed."""
    from mergecraft.main import owes_a_terminal_review

    class _State:
        terminal_submission = None
        selected_mode = "Review"

    assert not owes_a_terminal_review(_State())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("protocol", "received", "mode", "expected"),
    [
        ("shadow", True, "Review", "shadow"),
        ("enforce", False, "Review", "stale_attempt"),
        ("enforce", True, None, "not a review run"),
    ],
    ids=["shadow-protocol", "rejected-submission", "not-a-review-run"],
)
def test_every_way_a_recorded_verdict_reaches_no_review_names_itself(
    protocol: str,
    received: bool,
    mode: str | None,
    expected: str,
) -> None:
    from mergecraft.main import publication_skip_reason

    class _State:
        terminal_submission = object()
        selected_mode = mode

    result = AgentResult(
        success=True,
        terminal_submission_received=received,
        diagnostics={"rejection_reason": "stale_attempt"},
    )

    reason = publication_skip_reason(
        _State(),  # type: ignore[arg-type]
        result,
        verdict_protocol=protocol,
    )

    assert reason is not None
    assert expected in reason


@pytest.mark.asyncio
async def test_the_skip_reason_is_recorded_on_the_run_trajectory(tmp_path: Path) -> None:
    """The whole point: absence of a review is never silent again."""
    import mergecraft.main as main_mod

    ctx = await _state_with_a_recorded_verdict(tmp_path)
    result = AgentResult(
        success=True,
        terminal_submission_received=False,
        diagnostics={"rejection_reason": "stale_attempt"},
    )

    await main_mod._publish_recorded_verdict(ctx, result, verdict_protocol="enforce")

    rows = [
        call
        for call in ctx.tool_state.tool_calls
        if call.tool == main_mod._ORCHESTRATOR_PUBLISH_STEP
    ]
    assert len(rows) == 1, [call.tool for call in ctx.tool_state.tool_calls]
    assert rows[0].ok is False
    assert "stale_attempt" in (rows[0].error or "")


@pytest.mark.asyncio
async def test_a_run_that_recorded_nothing_records_no_publish_step(tmp_path: Path) -> None:
    """Nothing owed, nothing recorded — the guard the evidence suite also pins."""
    import mergecraft.main as main_mod

    ctx = _context(tmp_path, _Scm())

    await main_mod._publish_recorded_verdict(
        ctx,
        AgentResult(success=True),
        verdict_protocol="enforce",
    )

    assert [
        call
        for call in ctx.tool_state.tool_calls
        if call.tool == main_mod._ORCHESTRATOR_PUBLISH_STEP
    ] == []


@pytest.mark.asyncio
async def test_a_received_submission_is_still_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mergecraft.main as main_mod

    ctx = await _state_with_a_recorded_verdict(tmp_path)
    published: list[Any] = []

    async def _fake_publish(tool_context: Any) -> dict[str, Any]:
        published.append(tool_context)
        return {"success": True}

    monkeypatch.setattr("mergecraft.mcp.review.publish_pull_request_review", _fake_publish)

    await main_mod._publish_recorded_verdict(
        ctx,
        AgentResult(success=True, terminal_submission_received=True),
        verdict_protocol="enforce",
    )

    assert published == [ctx]
