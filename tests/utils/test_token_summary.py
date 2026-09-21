"""Published review token summaries split input and output (#801)."""

from __future__ import annotations

from mergecraft.agents.shared import AgentUsage
from mergecraft.utils.run_bounds import (
    BudgetTracker,
    RunBounds,
    format_token_budget_summary,
    record_agent_usage,
    token_summary_from_usage,
)


def _bounds() -> RunBounds:
    return RunBounds(
        token_budget=2_000_000,
        cost_budget_usd=50.0,
        tool_call_budget=500,
        run_timeout_s=60.0,
        context_retrieval_timeout_s=5.0,
        max_diff_lines=10_000,
        external_operation_timeout_s=30.0,
    )


def test_usage_entries_render_input_and_output() -> None:
    usage = [
        AgentUsage(agent="claude", input_tokens=12_345, output_tokens=2_100),
        AgentUsage(agent="claude", input_tokens=10, output_tokens=4),
    ]
    assert token_summary_from_usage(usage) == "12,355 input / 2,104 output"


def test_budget_tracker_summary_names_input_and_output() -> None:
    tracker = BudgetTracker(_bounds())
    usage = AgentUsage(agent="claude", input_tokens=12_345, output_tokens=2_100)
    record_agent_usage(tracker, usage, phase="reviewer_dispatch")
    summary = token_summary_from_usage([usage], budget_tracker=tracker)
    assert summary is not None
    assert "12,345 input / 2,100 output used" in summary
    assert "target 2,000,000" in summary
    assert "ceiling 2,000,000" in summary
    assert "14,445 used (" not in summary


def test_budget_tracker_without_split_still_shows_combined_used() -> None:
    tracker = BudgetTracker(_bounds())
    tracker.record_tokens(500, phase="context_expansion")
    summary = format_token_budget_summary(tracker)
    assert summary.startswith("500 used (target 2,000,000, ceiling 2,000,000)")
    assert "input /" not in summary


def test_split_and_unattributed_tokens_both_appear() -> None:
    tracker = BudgetTracker(_bounds())
    usage = AgentUsage(agent="claude", input_tokens=100, output_tokens=20)
    record_agent_usage(tracker, usage, phase="reviewer_dispatch")
    tracker.record_tokens(15, phase="context_expansion")
    summary = token_summary_from_usage([usage], budget_tracker=tracker)
    assert summary is not None
    assert summary.startswith("100 input / 20 output; 135 used (")


def test_review_record_renders_split_token_line() -> None:
    from mergecraft.evidence.build import build_packet
    from mergecraft.findings.ledger import render_deterministic_review_block

    packet = build_packet(
        change_id="acme/demo#801",
        agent_id="claude",
        agent_version="0.0.1",
        model="claude-sonnet-4-5",
        files_changed=["src/example.py"],
        findings=[],
        deterministic_checks=[],
    )
    tracker = BudgetTracker(_bounds())
    usage = AgentUsage(agent="claude", input_tokens=12_345, output_tokens=2_100)
    record_agent_usage(tracker, usage, phase="reviewer_dispatch")
    summary = token_summary_from_usage([usage], budget_tracker=tracker)
    block = render_deterministic_review_block(packet=packet, token_summary=summary)
    assert "- **Tokens:** 12,345 input / 2,100 output used" in block
    assert "14,445 used (" not in block
