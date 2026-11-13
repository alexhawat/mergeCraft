"""Phase 4 gates the verdict on changed-line coverage.

A run whose agent submitted a terminal verdict ends ``inconclusive`` (a ``neutral``
check) when any changed hunk never reached the reviewer, unless the repo opts into
``review.coverage.onIncomplete: warn``. Blockers still win on the approval check, and a
complete run is unchanged. Drives the real ``_finalize`` against a real tool context.

The native-read tests feed the real OpenCode stream consumer the events its ``read`` tool
emits, because the gate is only as true as what that consumer records.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.config.settings import RepoSettings
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.mcp.verdict import submit_review_verdict_tool
from mergecraft.run_outcome import RunOutcome
from tests.agents.test_driver_exec_recording import _lines, _NoopGroup, _Proc
from tests.support.finalize_harness import run_finalize
from tests.support.publication import (
    APP_DIFF,
    RecordingReviewGitHub,
    finding,
    publication_ctx,
    run_ctx_for,
    submit_verdict,
    unified_diff,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from mergecraft.mcp.context import ToolContext

_MISSING = unified_diff("src/never_delivered.py", start=10, count=5)


def _mark_read(ctx: ToolContext, path: str) -> None:
    """Record one successful source read so the run has observed read evidence."""
    from mergecraft.evidence.trajectory import record_tool_call

    record_tool_call(
        ctx.tool_state,
        tool="shell",
        arguments={"command": f"cat {path}"},
        ok=True,
    )


def _ctx_with_an_undelivered_hunk(tmp_path: Path) -> ToolContext:
    """A context whose authoritative PR diff holds a hunk the delivered diff lacks."""
    ctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    ctx.tool_state.coverage.authoritative_diff = APP_DIFF + _MISSING
    _mark_read(ctx, "src/app.py")
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
    _mark_read(ctx, "src/app.py")
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


# ── a driver's native reads ───────────────────────────────────────────────────


def _native_read(path: str, *, start: int = 1, end: int = 200) -> dict[str, object]:
    """One ``tool_use`` event as OpenCode 2.x's ``run --format json`` emits it."""
    return {
        "type": "tool_use",
        "sessionID": "ses_1",
        "part": {
            "type": "tool",
            "tool": "read",
            "state": {
                "status": "completed",
                "input": {"path": path},
                "output": f"Read file {path}, lines {start}-{end}\n{start}: x",
                "metadata": {"metadata": {"truncated": False}},
            },
        },
    }


_ANSWER = {"type": "text", "sessionID": "ses_1", "part": {"text": "done"}}


def _opencode_ctx(tmp_path: Path) -> ToolContext:
    """A context whose only reads will be the ones its OpenCode stream reports."""
    ctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    ctx.tool_state.tool_calls.clear()
    ctx.tool_state.coverage.authoritative_diff = APP_DIFF
    return ctx


def _opencode_stream(
    ctx: ToolContext, monkeypatch: pytest.MonkeyPatch, *events: dict[str, object]
) -> None:
    """Run one ``opencode run`` turn that emits ``events`` through the real consumer."""
    from mergecraft.agents import opencode as oc

    stream = _lines(*events, _ANSWER)
    monkeypatch.setattr(oc, "spawn_agent_cli", lambda *_a, **_k: _Proc(stream))
    monkeypatch.setattr(oc, "track_process_group", _NoopGroup)
    monkeypatch.setattr(oc, "wait_or_kill_process_group", lambda p, timeout: p.wait())

    result = oc._run_opencode_cli_streaming(
        cmd=["opencode"], ctx=run_ctx_for(ctx), env={}, session={}
    )

    assert result.success is True


def _diff_path(ctx: ToolContext) -> str:
    path = primary_repo_state(ctx.tool_state).diff_path
    assert path is not None
    return path


async def test_an_opencode_reviewer_that_reads_only_the_diff_natively_is_not_inconclusive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """sevn PR 21: ``shell: disabled``, a native read of ``diffPath``, ``Coverage: 0/4 hunks``."""
    ctx = _opencode_ctx(tmp_path)
    _opencode_stream(ctx, monkeypatch, _native_read(_diff_path(ctx)))
    await submit_verdict(ctx, "approve", [])

    record = await run_finalize(ctx, monkeypatch=monkeypatch, real_publish=True)

    assert record.outcome is RunOutcome.passed
    assert record.failure_reason is None
    packet = record.publish_calls[-1]["packet"]
    assert packet.coverage.complete is True
    assert packet.decision.verdict == "success", "a read of the diff attests a clean approve"


async def test_a_native_read_of_a_changed_source_file_counts_as_the_runs_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = _opencode_ctx(tmp_path)
    checkout = primary_repo_state(ctx.tool_state).dir
    _opencode_stream(ctx, monkeypatch, _native_read(f"{checkout}/src/app.py"))
    ctx.tool_state.diff_coverage_nudge_sent = True
    await submit_verdict(ctx, "approve", [])

    record = await run_finalize(ctx, monkeypatch=monkeypatch)

    assert record.outcome is RunOutcome.passed


async def test_a_reporting_driver_that_read_nothing_is_nudged_then_gated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The diff was written to disk and never opened, and here a read would have shown."""
    ctx = _opencode_ctx(tmp_path)
    _opencode_stream(ctx, monkeypatch)

    refused = await submit_review_verdict_tool(ctx).execute(
        {"verdict": "approve", "summary": "LGTM", "findings": []}
    )
    assert refused.is_error is True
    assert "src/app.py" in refused.content[0]["text"]

    await submit_verdict(ctx, "approve", [])
    record = await run_finalize(ctx, monkeypatch=monkeypatch, real_publish=True)

    assert record.outcome is RunOutcome.inconclusive
    packet = record.publish_calls[-1]["packet"]
    assert {row.cause for row in packet.coverage.uncovered} == {"not_observed"}
    assert packet.decision.verdict == "neutral"


async def test_the_nudge_lets_a_reviewer_that_read_nothing_recover(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = _opencode_ctx(tmp_path)
    _opencode_stream(ctx, monkeypatch)
    refused = await submit_review_verdict_tool(ctx).execute(
        {"verdict": "approve", "summary": "LGTM", "findings": []}
    )
    assert refused.is_error is True

    _opencode_stream(ctx, monkeypatch, _native_read(_diff_path(ctx)))
    await submit_verdict(ctx, "approve", [])
    record = await run_finalize(ctx, monkeypatch=monkeypatch)

    assert record.outcome is RunOutcome.passed


async def test_a_run_with_no_observed_read_never_goes_green(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The gap this gate guards, on a driver whose reads may just be invisible.

    Without the gate this run decides ``success``: ``no-post-edit-verification`` is a
    run-health row, and a run-health row attests. No nudge either, because no read
    the reviewer makes on such a driver could clear it.
    """
    ctx = _opencode_ctx(tmp_path)
    await submit_verdict(ctx, "approve", [])

    record = await run_finalize(ctx, monkeypatch=monkeypatch, real_publish=True)

    assert record.outcome is RunOutcome.inconclusive
    packet = record.publish_calls[-1]["packet"]
    assert {row.cause for row in packet.coverage.uncovered} == {"not_observed"}
    assert packet.decision.verdict == "neutral", "unknown is never green (#1056)"


async def test_a_native_read_never_clears_what_was_not_delivered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = _opencode_ctx(tmp_path)
    ctx.tool_state.coverage.authoritative_diff = APP_DIFF + _MISSING
    ctx.tool_state.coverage.unreviewable_paths = ["big/huge.py"]
    ctx.tool_state.coverage.diff_truncated = True
    _opencode_stream(ctx, monkeypatch, _native_read(_diff_path(ctx)))
    await submit_verdict(ctx, "approve", [])

    record = await run_finalize(ctx, monkeypatch=monkeypatch, real_publish=True)

    assert record.outcome is RunOutcome.inconclusive
    packet = record.publish_calls[-1]["packet"]
    assert {row.cause for row in packet.coverage.uncovered} == {
        "not_delivered",
        "no_inline_patch",
        "diff_truncated",
    }


def test_a_fallback_rung_does_not_inherit_the_reporting_of_the_rung_before_it(
    tmp_path: Path,
) -> None:
    from mergecraft.utils.agent_resolve import _prepare_chain_attempt

    ctx = _opencode_ctx(tmp_path)
    ctx.tool_state.driver_reports_reads = True

    _prepare_chain_attempt(ctx.tool_state, 1)

    assert ctx.tool_state.driver_reports_reads is False


async def test_diff_budget_omissions_withhold_approval_even_with_warn_coverage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A partial diff must not produce formal approval under an advisory policy."""
    github = RecordingReviewGitHub()
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted")
    await submit_verdict(ctx, "approve", [])
    ctx.tool_state.diff_budget_reason = "diff exceeded max_diff_lines; scope reduced"
    settings = RepoSettings.model_validate({"review": {"coverage": {"onIncomplete": "warn"}}})

    record = await run_finalize(ctx, monkeypatch=monkeypatch, settings=settings, real_publish=True)

    assert record.outcome is RunOutcome.inconclusive
    assert record.failure_reason == ctx.tool_state.diff_budget_reason
    assert github.review_payloads
    assert all(payload["event"] != "APPROVE" for payload in github.review_payloads)


async def test_incremental_progress_only_cannot_bypass_diff_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A progress summary cannot attest review of omitted incremental changes."""
    ctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    ctx.tool_state.selected_mode = "IncrementalReview"
    ctx.tool_state.final_summary_written = True
    ctx.tool_state.diff_budget_reason = "diff exceeded max_diff_lines; scope reduced"
    settings = RepoSettings.model_validate({"review": {"coverage": {"onIncomplete": "warn"}}})

    record = await run_finalize(ctx, monkeypatch=monkeypatch, settings=settings, real_publish=True)

    assert record.outcome is RunOutcome.inconclusive
    assert record.failure_reason == ctx.tool_state.diff_budget_reason
    assert record.publish_calls[-1]["packet"].decision.verdict != "success"
