"""The publish stage keeps the evidence packet complete and present (#1332).

Contracts:

- A publish-stage timeout that fires after the verdict reached GitHub still
  leaves an evidence packet, and the failure path's own publication is bounded.
- A primary that publishes its review mid-run does not freeze the packet: the
  findings the roster records afterwards are in the packet the run reports.

Both drive the real ``_finalize`` / ``_publish`` / ``_action_failure_result``
against the recording GitHub fake; the timeout comes from the real review
engine's stage bound, set tiny.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest

import mergecraft.main as main_mod
from mergecraft.agents.shared import AgentResult
from mergecraft.config.settings import RepoSettings
from mergecraft.mcp.review import create_pull_request_review_tool
from mergecraft.mcp.tool_state import record_reviewer_dispatch_run
from mergecraft.review.engine import ReviewEngine
from mergecraft.review.snapshot import canonical_review_snapshot
from mergecraft.run_outcome import RunOutcome
from tests.support.finalize_harness import run_finalize
from tests.support.publication import (
    RecordingReviewGitHub,
    finding,
    publication_ctx,
    run_ctx_for,
    submit_verdict,
)

_PRIMARY_BODY = "Verified Major: the retry loop never backs off."
_ROSTER_BODY = "Verified Major: the cache key ignores the tenant id."


class _SlowAfterAcceptGitHub(RecordingReviewGitHub):
    """GitHub accepts the review, then the response never comes back in time."""

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **payload: Any
    ) -> dict[str, Any]:
        await super().create_review(owner, repo, pull_number, **payload)
        await asyncio.sleep(30)  # cancelled by the stage bound well before this ends
        msg = "unreachable"
        raise AssertionError(msg)


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


async def _noop(*_args: Any, **_kwargs: Any) -> None:
    return None


async def test_publish_timeout_after_the_verdict_still_writes_the_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    github = _SlowAfterAcceptGitHub()
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted")
    await submit_verdict(ctx, "request_changes", [finding(_PRIMARY_BODY)])
    status_calls: list[dict[str, Any]] = []

    async def _record_status(_ctx: Any, **kwargs: Any) -> None:
        status_calls.append(kwargs)

    monkeypatch.setattr(main_mod, "report_status_checks", _record_status)
    monkeypatch.setattr(main_mod, "persist_learnings", _noop)
    monkeypatch.setattr(main_mod, "report_sarif_upload", _noop)
    monkeypatch.setattr(main_mod, "_FAILURE_PUBLISH_TIMEOUT_S", 0.3)
    run = main_mod.RunContext(
        settings=RepoSettings(),
        tool_context=ctx,
        tool_state=ctx.tool_state,
        run_ctx=run_ctx_for(ctx),
        tmpdir=ctx.tmpdir,
    )
    engine: ReviewEngine[Any] = ReviewEngine(snapshot=canonical_review_snapshot(entry="action"))

    started = time.monotonic()
    with pytest.raises(TimeoutError) as raised:
        await engine.run_stage(
            "publish",
            lambda: run.publish(AgentResult(success=True, output="ok")),
            timeout_s=0.3,
        )
    result = await main_mod._action_failure_result(run, raised.value)
    elapsed = time.monotonic() - started

    assert [payload["event"] for payload in github.review_payloads][:1] == ["REQUEST_CHANGES"]
    assert result.outcome is RunOutcome.timed_out
    assert elapsed < 10.0, f"the failure path took {elapsed:.1f}s; its publication is unbounded"
    assert result.evidence_packet_path is not None, "a publish timeout lost the evidence packet"
    packet_text = _read_text(result.evidence_packet_path)
    assert _PRIMARY_BODY in packet_text
    json.loads(packet_text)


async def test_failure_before_the_publish_stage_writes_no_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: a failure before the review finished keeps the old failure path."""
    ctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    emitted: list[Any] = []
    monkeypatch.setattr(main_mod, "emit_run_packet", lambda *a, **k: emitted.append(a))
    monkeypatch.setattr(main_mod, "report_status_checks", _noop)
    monkeypatch.setattr(main_mod, "persist_learnings", _noop)
    run = main_mod.RunContext(settings=RepoSettings(), tool_context=ctx, tool_state=ctx.tool_state)

    result = await main_mod._action_failure_result(run, TimeoutError("agent timed out"))

    assert result.outcome is RunOutcome.timed_out
    assert result.evidence_packet_path is None
    assert emitted == []


async def test_mid_run_publication_does_not_freeze_the_packet_before_the_roster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    github = RecordingReviewGitHub()
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted")
    await submit_verdict(ctx, "request_changes", [finding(_PRIMARY_BODY)])
    submission = ctx.tool_state.terminal_submission
    assert submission is not None
    # The primary publishes its own review mid-run, before the roster runs.
    published = await create_pull_request_review_tool(ctx).execute(
        {"pull_number": 7, "body": submission.summary, "request_changes": True}
    )
    assert published.is_error is False
    assert ctx.tool_state.prepared_run_packet is not None
    # The server-side roster then records a secondary reviewer's finding.
    record_reviewer_dispatch_run(
        ctx.tool_state,
        agent_id="reviewer2",
        findings=[finding(_ROSTER_BODY, line=14)],
    )

    record = await run_finalize(ctx, monkeypatch=monkeypatch, real_publish=True)

    reported = record.publish_calls[-1]["packet"]
    assert reported is not None
    bodies = json.dumps(reported.model_dump(mode="json"))
    assert _ROSTER_BODY in bodies, "the roster's finding is missing from the run's packet"
    assert _PRIMARY_BODY in bodies
