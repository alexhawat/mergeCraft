"""An open analyzer disposition ledger reaches the completion check (#1014).

``outcome_with_disposition_ledger`` is unit-tested next to the packet. These
tests drive the two places it is wired — ``_publish`` (the status checks) and
``_finalize`` (the run's own ``MainResult``) — through the real Phase-4 path,
so a ledger that loses a raw hit cannot leave the completion check at
``success`` while the approval check reads ``neutral``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.run_outcome import RunOutcome
from tests.evidence.test_packet_dispositions import _closed_ledger, _hit, _record
from tests.support.finalize_harness import run_finalize
from tests.support.publication import RecordingReviewGitHub, publication_ctx, submit_verdict

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.mcp.context import ToolContext


async def _approved_run(tmp_path: Path, *, orphaned: bool) -> ToolContext:
    ctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="trusted")
    kept = [_hit(line=3)]
    lost = [_hit(line=4, message="swallowed by a stage")] if orphaned else []
    _record(ctx, kept, _closed_ledger(kept, lost=lost))
    await submit_verdict(ctx, "approve", [], summary="Looks good.")
    return ctx


def _status_call(publish_calls: list[dict[str, Any]]) -> dict[str, Any]:
    assert publish_calls, "the real _publish must post the status checks"
    return publish_calls[-1]


@pytest.mark.asyncio
async def test_an_open_ledger_makes_the_completion_check_neutral(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = await _approved_run(tmp_path, orphaned=True)

    record = await run_finalize(ctx, monkeypatch=monkeypatch, real_publish=True)

    status = _status_call(record.publish_calls)
    assert status["conclusion"] == "neutral"
    assert status["run_succeeded"] is False
    assert "ledger open" in str(status["failure_reason"])
    assert record.outcome is RunOutcome.inconclusive
    assert record.result.success is False
    assert "ledger open" in str(record.result.error)


@pytest.mark.asyncio
async def test_a_closed_ledger_keeps_the_completion_check_successful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: the same run with every hit accounted for still passes."""
    ctx = await _approved_run(tmp_path, orphaned=False)

    record = await run_finalize(ctx, monkeypatch=monkeypatch, real_publish=True)

    status = _status_call(record.publish_calls)
    assert status["conclusion"] == "success"
    assert record.outcome is RunOutcome.passed
