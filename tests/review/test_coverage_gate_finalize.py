"""Phase 4 gates the verdict on changed-line coverage.

A run whose agent submitted a terminal verdict ends ``inconclusive`` (a ``neutral``
check) when any changed hunk never reached the reviewer, unless the repo opts into
``review.coverage.onIncomplete: warn``. Blockers still win on the approval check, and a
complete run is unchanged. Drives the real ``_finalize`` against a real tool context.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.config.settings import RepoSettings
from mergecraft.run_outcome import RunOutcome
from tests.support.finalize_harness import run_finalize
from tests.support.publication import (
    APP_DIFF,
    RecordingReviewGitHub,
    finding,
    publication_ctx,
    submit_verdict,
    unified_diff,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from mergecraft.mcp.context import ToolContext

_MISSING = unified_diff("src/never_delivered.py", start=10, count=5)


def _ctx_with_an_undelivered_hunk(tmp_path: Path) -> ToolContext:
    """A context whose authoritative PR diff holds a hunk the delivered diff lacks."""
    ctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    ctx.tool_state.coverage.authoritative_diff = APP_DIFF + _MISSING
    return ctx


async def test_an_undelivered_hunk_makes_a_submitted_verdict_inconclusive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = _ctx_with_an_undelivered_hunk(tmp_path)
    await submit_verdict(ctx, "approve", [])

    record = await run_finalize(ctx, monkeypatch=monkeypatch)

    assert record.outcome is RunOutcome.inconclusive
    assert record.failure_reason is not None
    assert "Coverage: 1/2 hunks, 1 uncovered" in record.failure_reason
    assert "src/never_delivered.py" in record.failure_reason


async def test_the_warn_policy_keeps_the_verdict_and_still_reports_the_gap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = _ctx_with_an_undelivered_hunk(tmp_path)
    await submit_verdict(ctx, "approve", [])
    settings = RepoSettings.model_validate({"review": {"coverage": {"onIncomplete": "warn"}}})

    record = await run_finalize(ctx, monkeypatch=monkeypatch, settings=settings)

    assert record.outcome is RunOutcome.passed


async def test_a_fully_delivered_diff_leaves_the_outcome_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    ctx.tool_state.coverage.authoritative_diff = APP_DIFF
    await submit_verdict(ctx, "approve", [])

    record = await run_finalize(ctx, monkeypatch=monkeypatch)

    assert record.outcome is RunOutcome.passed
    assert record.failure_reason is None


async def test_a_blocker_on_an_incomplete_run_still_fails_the_approval_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = _ctx_with_an_undelivered_hunk(tmp_path)
    await submit_verdict(
        ctx, "request_changes", [finding("Verified Major: the retry loop never backs off.")]
    )

    record = await run_finalize(ctx, monkeypatch=monkeypatch, real_publish=True)

    assert record.outcome is RunOutcome.inconclusive
    packet = record.publish_calls[-1]["packet"]
    assert packet.decision is not None
    assert packet.decision.verdict == "failure", "a blocker is never masked by incomplete coverage"
    assert packet.coverage is not None
    assert packet.coverage.complete is False


async def test_the_recorded_packet_says_what_was_uncovered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = _ctx_with_an_undelivered_hunk(tmp_path)
    await submit_verdict(ctx, "approve", [])

    record = await run_finalize(ctx, monkeypatch=monkeypatch, real_publish=True)

    packet = record.publish_calls[-1]["packet"]
    assert [(r.path, r.cause) for r in packet.coverage.uncovered] == [
        ("src/never_delivered.py", "not_delivered")
    ]
    assert record.publish_calls[-1]["conclusion"] == "neutral"
