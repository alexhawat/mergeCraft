"""An accepted verdict publishes the run record even when no mode was selected.

PR #1021's OpenCode Go rung recorded ``submit_review_verdict`` without ever
calling ``select_mode``. ``selected_mode`` stayed ``None``, so every Review-mode
gate read false: ``_publish_recorded_verdict`` returned early and ``_publish``
skipped ``publish_deterministic_record``. The PR got only the progress comment,
and the run record (tokens, cost, generation time, findings) never landed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.agents.shared import AgentUsage
from mergecraft.mcp.verdict import submit_review_verdict_tool
from tests.review_record.test_w15_deterministic_record import (
    _context,
    _publish_deterministic_record,
    _sample_packet,
    _Scm,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_accepted_verdict_without_select_mode_marks_the_run_as_review(
    tmp_path: Path,
) -> None:
    ctx = _context(tmp_path, _Scm())
    assert ctx.tool_state.selected_mode is None

    result = await submit_review_verdict_tool(ctx).execute(
        {"verdict": "approve", "summary": "No blocking issues.", "findings": []}
    )

    assert result.is_error is False
    assert ctx.tool_state.terminal_submission is not None
    assert ctx.tool_state.selected_mode == "Review"


@pytest.mark.asyncio
async def test_rejected_verdict_without_select_mode_leaves_the_mode_unset(
    tmp_path: Path,
) -> None:
    ctx = _context(tmp_path, _Scm())

    result = await submit_review_verdict_tool(ctx).execute({"verdict": "maybe", "summary": "x"})

    assert result.is_error is True
    assert ctx.tool_state.selected_mode is None


@pytest.mark.asyncio
async def test_explicitly_selected_mode_is_not_overwritten(tmp_path: Path) -> None:
    ctx = _context(tmp_path, _Scm())
    ctx.tool_state.selected_mode = "IncrementalReview"
    ctx.tool_state.review_phase = "submit"

    await submit_review_verdict_tool(ctx).execute(
        {"verdict": "approve", "summary": "No blocking issues.", "findings": []}
    )

    assert ctx.tool_state.selected_mode == "IncrementalReview"


@pytest.mark.asyncio
async def test_progress_after_a_modeless_submission_stays_in_the_formal_review(
    tmp_path: Path,
) -> None:
    """#868 retired the separate progress comment for Review runs; #1021 still got one."""
    from mergecraft.mcp.comment import report_progress_tool

    scm = _Scm()
    ctx = _context(tmp_path, scm)
    await submit_review_verdict_tool(ctx).execute(
        {"verdict": "approve", "summary": "No blocking issues.", "findings": []}
    )

    result = await report_progress_tool(ctx).execute({"body": "Review complete."})

    assert result.is_error is False
    assert scm.comment_creates == 0
    assert ctx.tool_state.final_summary_written is True


@pytest.mark.asyncio
async def test_publish_posts_the_run_record_after_a_modeless_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``_publish`` gate that skipped the record on #1021 now lets it through."""
    import mergecraft.main as main_mod
    import mergecraft.utils.step_summary as step_summary_mod
    from mergecraft.main import RunOutcome

    ctx = _context(tmp_path, _Scm())
    await submit_review_verdict_tool(ctx).execute(
        {"verdict": "approve", "summary": "No blocking issues.", "findings": []}
    )
    calls: list[dict[str, Any]] = []

    async def _capture(**kwargs: Any) -> None:
        calls.append(kwargs)

    async def _noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(main_mod, "persist_learnings", _noop)
    monkeypatch.setattr(main_mod, "report_status_checks", _noop)
    monkeypatch.setattr(main_mod, "publish_deterministic_record", _capture)
    monkeypatch.setattr(step_summary_mod, "append_step_summary", lambda _body: None)

    run_ctx = main_mod.RunContext(tool_context=ctx)
    await main_mod._publish(
        run_ctx, outcome=RunOutcome.failed, failure_reason="opencode failed", emit=False
    )

    assert len(calls) == 1
    assert calls[0]["pull_number"] == 546


@pytest.mark.asyncio
async def test_run_record_carries_the_cost_line(tmp_path: Path) -> None:
    """``publish_deterministic_record`` renders the Cost line the step summary already shows."""
    scm = _Scm()
    ctx = _context(tmp_path, scm)
    ctx.tool_state.usage_entries = [
        AgentUsage(agent="opencode", input_tokens=1_000, output_tokens=100, cost_usd=0.0123)
    ]

    await _publish_deterministic_record()(
        pull_number=546,
        packet=_sample_packet(findings=[], verdict="success", reason="approved"),
        ctx=ctx,
    )

    assert "- **Cost:** $0.0123" in scm.reviews[1]
