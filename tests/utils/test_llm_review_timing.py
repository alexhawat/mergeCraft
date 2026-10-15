"""LLM review generation timing (#983 task 6)."""

from __future__ import annotations

from mergecraft.evidence.build import build_packet
from mergecraft.findings.ledger import render_deterministic_review_block
from mergecraft.utils.llm_review_timing import (
    LlmReviewTimingSnapshot,
    bind_llm_review_timing_tracker,
    format_llm_review_timing_line,
    snapshot_llm_review_timing,
)
from mergecraft.utils.step_summary import render_step_summary


def test_multi_reviewer_timing_line_includes_total_and_wall() -> None:
    snapshot = LlmReviewTimingSnapshot(
        per_reviewer_seconds=(("mergecraft-reviewer", 120.0), ("reviewer2", 71.0)),
        total_llm_seconds=191.0,
        wall_seconds=150.0,
    )
    line = format_llm_review_timing_line(snapshot)
    assert line.startswith("⏱ LLM review time: 3m 11s total (")
    assert "mergecraft-reviewer 2m 0s" in line
    assert "reviewer2 1m 11s" in line
    assert "wall 2m 30s" in line


def test_deterministic_record_includes_llm_review_timing() -> None:
    packet = build_packet(
        change_id="acme/demo#983",
        agent_id="claude",
        agent_version="0.0.1",
        model="claude-sonnet-4-5",
        files_changed=["src/example.py"],
        findings=[],
        deterministic_checks=[],
    )
    snapshot = LlmReviewTimingSnapshot(
        per_reviewer_seconds=(("mergecraft-reviewer", 191.0),),
        total_llm_seconds=191.0,
        wall_seconds=191.0,
    )
    block = render_deterministic_review_block(packet=packet, llm_review_timing=snapshot)
    assert "⏱ LLM review time: 3m 11s" in block


def test_step_summary_includes_llm_review_timing() -> None:
    packet = build_packet(
        change_id="acme/demo#983",
        agent_id="claude",
        agent_version="0.0.1",
        model="claude-sonnet-4-5",
        files_changed=["src/example.py"],
        findings=[],
        deterministic_checks=[],
    )
    snapshot = LlmReviewTimingSnapshot(
        per_reviewer_seconds=(("mergecraft-reviewer", 45.0),),
        total_llm_seconds=45.0,
        wall_seconds=45.0,
    )
    body = render_step_summary(
        packet=packet,
        outcome_label="success",
        llm_review_timing=snapshot,
    )
    assert "⏱ LLM review time: 45s" in body


def test_model_chain_fallback_accumulates_same_reviewer() -> None:
    import time

    tracker = bind_llm_review_timing_tracker()
    tracker.note_unbound_llm_call_start()
    time.sleep(0.01)
    tracker.note_generation_end("claude", role="reviewer")
    tracker.note_unbound_llm_call_start()
    time.sleep(0.01)
    tracker.note_generation_end("claude", role="reviewer")
    snapshot = snapshot_llm_review_timing(tracker)
    assert snapshot is not None
    assert snapshot.per_reviewer_seconds == (("claude", snapshot.total_llm_seconds),)
    assert snapshot.total_llm_seconds >= 0.02


def test_unbound_llm_call_before_agent_run_attributes_on_reviewer_end() -> None:
    import time

    tracker = bind_llm_review_timing_tracker()
    tracker.note_unbound_llm_call_start()
    time.sleep(0.01)
    tracker.note_generation_end("claude", role="reviewer")
    snapshot = snapshot_llm_review_timing(tracker)
    assert snapshot is not None
    assert snapshot.total_llm_seconds > 0
    assert snapshot.per_reviewer_seconds[0][0] == "claude"


def test_tracker_snapshots_from_llm_call_and_reviewer_end() -> None:
    tracker = bind_llm_review_timing_tracker()
    tracker.note_llm_call_start("mergecraft-reviewer")
    tracker.note_generation_end("mergecraft-reviewer", role="reviewer")
    snapshot = snapshot_llm_review_timing(tracker)
    assert snapshot is not None
    assert snapshot.total_llm_seconds >= 0.0
    assert snapshot.per_reviewer_seconds[0][0] == "mergecraft-reviewer"


def test_cli_json_envelope_carries_llm_review_timing(capsys) -> None:
    import json

    from mergecraft.cli.review_output import emit_review_json_stdout

    timing = {
        "per_reviewer": {"mergecraft-reviewer": 11.0},
        "total_llm_seconds": 11.0,
        "wall_seconds": 11.0,
        "line": "⏱ LLM review time: 11s",
    }
    emit_review_json_stdout(
        review_id="local-test",
        findings=[],
        output_text="summary",
        llm_review_timing=timing,
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["llm_review_timing"]["line"] == "⏱ LLM review time: 11s"
