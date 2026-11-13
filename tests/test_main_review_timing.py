"""Action timing starts before the reviewer selects its mode."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.agents.shared import AgentResult
from mergecraft.utils.llm_review_timing import (
    clear_llm_review_timing_tracker,
    get_llm_review_timing_tracker,
    note_llm_call_started,
)
from tests.support.run_main_harness import FakeAgent, run_main_for_test

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


async def test_action_records_generation_when_mode_is_selected_during_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_llm_review_timing_tracker()
    trackers = []

    class Agent(FakeAgent):
        async def run(self, ctx: Any) -> AgentResult:
            assert ctx.tool_state.selected_mode is None
            trackers.append(get_llm_review_timing_tracker())
            note_llm_call_started()
            ctx.tool_state.selected_mode = "Review"
            return AgentResult(success=True)

    try:
        rec = await run_main_for_test(monkeypatch=monkeypatch, tmp_path=tmp_path, agent=Agent())
        assert rec.raised is None
        assert trackers
        assert trackers[0] is not None
        assert rec.tool_context.tool_state.llm_review_timing is not None
        assert rec.tool_context.tool_state.llm_review_timing.total_llm_seconds > 0
    finally:
        clear_llm_review_timing_tracker()
