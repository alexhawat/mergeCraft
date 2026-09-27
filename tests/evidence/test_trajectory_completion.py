"""A compliant Review run's trajectory has a completion step.

After publication moved to the orchestrator, a compliant Review run calls
``submit_review_verdict`` and never ``create_pull_request_review`` — which used
to be the only review-mode ``complete`` intent. Two things keep the trajectory
honest: ``submit_review_verdict`` maps to ``complete``, and the orchestrator's
publish records a synthetic call ``orchestrator.publish_review`` (intent
``complete``, ``ok`` = a receipt is present). A run whose review never reached
GitHub therefore carries no successful publish step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.evidence.trajectory import (
    build_trajectory_record,
    classify_tool_intent,
    record_tool_call,
)
from tests.support.finalize_harness import run_finalize
from tests.support.publication import (
    RecordingReviewGitHub,
    finding,
    publication_ctx,
    submit_verdict,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.mcp.context import ToolContext

_ORCHESTRATOR_PUBLISH = "orchestrator.publish_review"

_GREEN_AFTER_INTENT_MAP = pytest.mark.xfail(
    reason="green after VP2.4: submit_review_verdict maps to the complete intent",
    strict=False,
)
_GREEN_AFTER_SYNTHETIC_PUBLISH = pytest.mark.xfail(
    reason="green after VP2.4 + VP2.5: the orchestrator publish is a trajectory step",
    strict=False,
)


async def _submit_like_the_agent(ctx: ToolContext) -> None:
    """Record the verdict and the mediated tool call the MCP server would log for it."""
    summary = "One finding stands."
    findings = [finding("Unchecked index.")]
    payload: dict[str, Any] = {
        "verdict": "request_changes",
        "summary": summary,
        "findings": findings,
    }
    await submit_verdict(ctx, "request_changes", findings, summary=summary)
    record_tool_call(ctx.tool_state, tool="submit_review_verdict", arguments=payload, ok=True)


@_GREEN_AFTER_INTENT_MAP
def test_submit_review_verdict_is_a_completion_intent() -> None:
    assert classify_tool_intent("submit_review_verdict", {"verdict": "approve"}) == "complete"


def test_create_pull_request_review_is_still_a_completion_intent() -> None:
    """Green guard: the legacy publishing tool keeps its intent."""
    assert classify_tool_intent("create_pull_request_review", {}) == "complete"


def test_an_unknown_tool_is_never_counted_as_completion() -> None:
    """Green guard: the map is explicit; nothing falls into ``complete`` by accident."""
    assert classify_tool_intent("orchestrator.something_else", {}) == "other"


@_GREEN_AFTER_SYNTHETIC_PUBLISH
@pytest.mark.asyncio
async def test_a_compliant_run_published_by_the_orchestrator_has_a_complete_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    github = RecordingReviewGitHub()
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted")
    await _submit_like_the_agent(ctx)

    await run_finalize(ctx, monkeypatch=monkeypatch)

    publish_rows = [
        call for call in ctx.tool_state.tool_calls if call.tool == _ORCHESTRATOR_PUBLISH
    ]
    assert len(publish_rows) == 1
    assert publish_rows[0].intent == "complete"
    assert publish_rows[0].ok is True
    record = build_trajectory_record(ctx.tool_state)
    assert _ORCHESTRATOR_PUBLISH in record.completion_claims
    assert "submit_review_verdict" in record.completion_claims
    assert "create_pull_request_review" not in [call.tool for call in record.tool_calls]


@_GREEN_AFTER_SYNTHETIC_PUBLISH
@pytest.mark.asyncio
async def test_a_run_with_no_receipt_has_no_successful_publish_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Error: GitHub refused the POST -> the publish step is recorded, not ok, not a claim."""
    github = RecordingReviewGitHub(create_failures=1)
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted")
    await _submit_like_the_agent(ctx)

    await run_finalize(ctx, monkeypatch=monkeypatch)

    assert ctx.tool_state.review is None
    publish_rows = [
        call for call in ctx.tool_state.tool_calls if call.tool == _ORCHESTRATOR_PUBLISH
    ]
    assert len(publish_rows) == 1
    assert publish_rows[0].intent == "complete"
    assert publish_rows[0].ok is False
    assert _ORCHESTRATOR_PUBLISH not in build_trajectory_record(ctx.tool_state).completion_claims


@pytest.mark.asyncio
async def test_a_run_that_never_submitted_records_no_publish_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Edge (green guard): nothing was recorded, so the orchestrator has nothing to publish."""
    github = RecordingReviewGitHub()
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted")

    await run_finalize(ctx, monkeypatch=monkeypatch)

    assert github.review_payloads == []
    assert all(call.tool != _ORCHESTRATOR_PUBLISH for call in ctx.tool_state.tool_calls)
    assert build_trajectory_record(ctx.tool_state).completion_claims == []
