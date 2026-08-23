"""Lens execution recording (RC7) — W5.1 RED suite.

Wave plan: ``.ignorelocal/waves/review-convergence-wave-plan.md`` (W5).
Pins ``ToolState`` lens fields and review-metadata round-trip helpers
implemented in W5.2 (``mcp/tool_state.py``, ``modes/_pr_summary_format.py``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.review.lens_routing import LensRoutingDecision, LensRoutingEntry


def _tool_state_mod() -> Any:
    import mergecraft.mcp.tool_state as mod

    return mod


def _pr_summary_mod() -> Any:
    from mergecraft.modes import _pr_summary_format as mod

    return mod


def _sample_routing_decision() -> LensRoutingDecision:
    return LensRoutingDecision(
        selected_lens_ids=("security", "schema-migration", "performance"),
        entries=(
            LensRoutingEntry(
                lens_id="security",
                selected=True,
                reason="categories auth_security_payment",
            ),
            LensRoutingEntry(
                lens_id="schema-migration",
                selected=True,
                reason="categories migrations",
            ),
            LensRoutingEntry(
                lens_id="performance",
                selected=True,
                reason="categories source_without_tests",
            ),
            LensRoutingEntry(
                lens_id="holistic",
                selected=False,
                reason="risk_band low below minRiskBand medium",
            ),
        ),
    )


def test_routing_decision_is_written_to_tool_state(tmp_path: Path) -> None:
    """RC7 — the full ``LensRoutingDecision`` is stored on ``ToolState``."""
    tool_state_mod = _tool_state_mod()
    record_lens_execution = tool_state_mod.record_lens_execution
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    decision = _sample_routing_decision()

    record_lens_execution(
        state,
        routing_decision=decision,
        dispatched_lens_ids=("security", "schema-migration"),
    )

    assert state.lens_routing_decision == decision
    assert state.lens_routing_decision.entries == decision.entries


def test_dispatched_lens_ids_are_recorded_not_just_recommended(tmp_path: Path) -> None:
    """Recommended (routed) lenses and actually-dispatched lenses must diverge."""
    tool_state_mod = _tool_state_mod()
    record_lens_execution = tool_state_mod.record_lens_execution
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    decision = _sample_routing_decision()
    dispatched = ("security", "schema-migration")

    record_lens_execution(
        state,
        routing_decision=decision,
        dispatched_lens_ids=dispatched,
    )

    assert set(decision.selected_lens_ids) > set(dispatched)
    assert state.dispatched_lens_ids == dispatched
    assert state.dispatched_lens_ids != decision.selected_lens_ids


def test_skipped_lenses_and_reasons_are_recorded(tmp_path: Path) -> None:
    """Skipped lenses stay on the decision with non-empty reasons."""
    tool_state_mod = _tool_state_mod()
    record_lens_execution = tool_state_mod.record_lens_execution
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    decision = _sample_routing_decision()

    record_lens_execution(
        state,
        routing_decision=decision,
        dispatched_lens_ids=("security",),
    )

    recorded = {entry.lens_id: entry for entry in state.lens_routing_decision.entries}
    skipped = [entry for entry in decision.entries if not entry.selected]
    assert skipped, "fixture must include at least one skipped lens"
    for entry in skipped:
        assert recorded[entry.lens_id].selected is False
        assert recorded[entry.lens_id].reason.strip()


def test_lens_set_is_serialized_into_review_metadata() -> None:
    """Dispatched lens ids must round-trip through the review metadata comment."""
    pr_summary = _pr_summary_mod()
    merge_dispatched_lenses_into_review_metadata = (
        pr_summary.merge_dispatched_lenses_into_review_metadata
    )
    parse_dispatched_lenses_from_review_body = pr_summary.parse_dispatched_lenses_from_review_body

    preamble = (
        "**Reviewed changes** — billing and migration edits.\n\n"
        "<!--\n"
        "mergeCraft review metadata\n"
        "- Mode: Review\n"
        "- Head: feature/billing (abc1234)\n"
        "-->\n"
    )
    dispatched = ("security", "schema-migration")

    merged = merge_dispatched_lenses_into_review_metadata(
        preamble,
        dispatched_lens_ids=dispatched,
    )
    restored = parse_dispatched_lenses_from_review_body(merged)

    assert restored == dispatched
    assert "security" in merged
    assert "schema-migration" in merged
