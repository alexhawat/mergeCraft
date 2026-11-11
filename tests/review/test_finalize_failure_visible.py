"""A post-run finalize failure is visible in the log and in the run record.

``_finalize`` wraps ``finalize_agent_result`` so a failure there cannot crash the
publish phase. It used to log at ``debug`` and carry on, so the operator saw a
missing verdict with no hint that the cause was a finalize error. The run must
still fail closed (``inconclusive`` for a Review run); what changes is that the
failure is a ``warning`` naming the exception type and the record names it too.

Each case hands ``_finalize`` what a real driver returns: a result already passed
through ``finalize_agent_result`` (``terminal_submission_received=True``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

import mergecraft.main as main_mod
from mergecraft.agents.post_run import finalize_agent_result
from mergecraft.agents.shared import AgentResult
from mergecraft.run_outcome import RunOutcome
from tests.support.finalize_harness import run_finalize
from tests.support.publication import (
    RecordingReviewGitHub,
    publication_ctx,
    run_ctx_for,
    submit_verdict,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class _FinalizeBoom(RuntimeError):
    """A distinctive type so the assertions cannot match an unrelated message."""


async def _raise_finalize(*_args: Any, **_kwargs: Any) -> Any:
    msg = "terminal fields could not be read"
    raise _FinalizeBoom(msg)


async def _driver_result(ctx: Any) -> AgentResult:
    """What a real driver hands ``_finalize``: an already-finalized result."""
    result = await finalize_agent_result(run_ctx_for(ctx), AgentResult(success=True, output="ok"))
    assert result.terminal_submission_received is True
    return result


def _warnings() -> tuple[list[str], int]:
    captured: list[str] = []
    sink_id = logger.add(lambda message: captured.append(str(message)), level="WARNING")
    return captured, sink_id


async def test_finalize_failure_logs_a_warning_naming_the_exception_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    await submit_verdict(ctx, "approve", [])
    driver_result = await _driver_result(ctx)
    monkeypatch.setattr(main_mod, "finalize_agent_result", _raise_finalize)
    captured, sink_id = _warnings()
    try:
        await run_finalize(ctx, monkeypatch=monkeypatch, agent_result=driver_result)
    finally:
        logger.remove(sink_id)

    assert any("_FinalizeBoom" in line and "finalize" in line.lower() for line in captured), (
        captured
    )


async def test_finalize_failure_still_fails_closed_and_names_itself_as_the_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    github = RecordingReviewGitHub()
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted", pr_approve_enabled=True)
    ctx.authority_trust = "trusted"
    await submit_verdict(ctx, "approve", [])
    driver_result = await _driver_result(ctx)
    monkeypatch.setattr(main_mod, "finalize_agent_result", _raise_finalize)

    record = await run_finalize(ctx, monkeypatch=monkeypatch, agent_result=driver_result)

    assert record.outcome is RunOutcome.inconclusive
    assert record.failure_reason is not None
    assert "finalize_failed: _FinalizeBoom" in record.failure_reason
    assert github.review_payloads == []


async def test_the_published_run_record_names_the_finalize_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    github = RecordingReviewGitHub()
    ctx = publication_ctx(tmp_path, github=github, trust_tier="trusted")
    await submit_verdict(ctx, "approve", [])
    driver_result = await _driver_result(ctx)
    monkeypatch.setattr(main_mod, "finalize_agent_result", _raise_finalize)

    await run_finalize(ctx, monkeypatch=monkeypatch, agent_result=driver_result, real_publish=True)

    bodies = "\n".join(github.review_bodies.values())
    assert "finalize_failed: _FinalizeBoom" in bodies


async def test_a_finalize_that_succeeds_logs_no_finalize_warning_and_keeps_its_outcome(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    await submit_verdict(ctx, "approve", [])
    driver_result = await _driver_result(ctx)
    captured, sink_id = _warnings()
    try:
        record = await run_finalize(ctx, monkeypatch=monkeypatch, agent_result=driver_result)
    finally:
        logger.remove(sink_id)

    assert not any("finalize" in line.lower() and "failed" in line.lower() for line in captured)
    assert record.failure_reason is None or "finalize_failed" not in record.failure_reason
