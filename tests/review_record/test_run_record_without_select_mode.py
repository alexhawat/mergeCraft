"""An accepted verdict publishes the run record even when no mode was selected.

PR #1021's OpenCode Go rung recorded ``submit_review_verdict`` without ever
calling ``select_mode``. ``selected_mode`` stayed ``None``, so every Review-mode
gate read false: ``_publish_recorded_verdict`` returned early and ``_publish``
skipped ``publish_deterministic_record``. The PR got only the progress comment,
and the run record (tokens, cost, generation time, findings) never landed.

A modeless verdict is adopted as a Review, so it needs review scope like any
Review verdict: the accepted-verdict cases here establish scope first, and a
modeless verdict without scope is refused.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.agents._stream_consumer import StreamSpanAccumulator
from mergecraft.agents.opencode import _session_event_handler
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


def _scoped_context(tmp_path: Path, scm: _Scm) -> Any:
    """Return the modeless context with checkout-backed review scope registered."""
    from mergecraft.mcp.verdict import register_review_scope

    ctx = _context(tmp_path, scm)
    diff = tmp_path / "pr.diff"
    diff.write_text(
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n",
        encoding="utf-8",
    )
    register_review_scope(ctx.tool_state, diff_path=str(diff), provenance="checkout")
    return ctx


@pytest.mark.asyncio
async def test_a_modeless_verdict_without_review_scope_is_refused(tmp_path: Path) -> None:
    from mergecraft.mcp.verdict import REJECTION_SCOPE_UNAVAILABLE

    ctx = _context(tmp_path, _Scm())
    assert ctx.tool_state.selected_mode is None

    result = await submit_review_verdict_tool(ctx).execute(
        {"verdict": "approve", "summary": "No blocking issues.", "findings": []}
    )

    assert result.is_error is True
    assert "requires review scope" in result.content[0]["text"]
    assert ctx.tool_state.terminal_submission is None
    assert ctx.tool_state.last_terminal_rejection == REJECTION_SCOPE_UNAVAILABLE
    assert ctx.tool_state.selected_mode is None


@pytest.mark.asyncio
async def test_accepted_verdict_without_select_mode_marks_the_run_as_review(
    tmp_path: Path,
) -> None:
    ctx = _scoped_context(tmp_path, _Scm())
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
    ctx = _scoped_context(tmp_path, _Scm())

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
    ctx = _scoped_context(tmp_path, scm)
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

    ctx = _scoped_context(tmp_path, _Scm())
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


@pytest.mark.parametrize("with_budget", [False, True])
async def test_go_estimate_reaches_the_published_record(tmp_path: Path, with_budget: bool) -> None:
    """Publication preserves the subscription qualification with either cost source."""
    from mergecraft.utils.run_bounds import BudgetTracker, resolve_run_bounds

    accumulator = StreamSpanAccumulator(agent_name="opencode")
    handler = _session_event_handler({}, model="opencode-go/deepseek-v4.1-flash")
    handler(
        accumulator,
        {
            "type": "step_finish",
            "timestamp": 1793491200000,
            "part": {
                "cost": 0,
                "tokens": {
                    "input": 1_000_000,
                    "output": 1_000_000,
                    "cache": {"read": 1_000_000},
                },
            },
        },
    )
    usage = accumulator.to_usage()
    assert usage is not None
    scm = _Scm()
    ctx = _context(tmp_path, scm)
    ctx.tool_state.usage_entries = [usage]
    if with_budget:
        tracker = BudgetTracker(resolve_run_bounds(env={}))
        tracker.record_cost(usage.cost_usd or 0)
        ctx.budget_tracker = tracker
    await _publish_deterministic_record()(
        pull_number=546,
        packet=_sample_packet(findings=[], verdict="success", reason="approved"),
        ctx=ctx,
    )
    assert (
        "- **Cost:** $0.7530 (includes estimated OpenCode Go usage value; "
        "subscription billed separately)"
    ) in scm.reviews[1]
