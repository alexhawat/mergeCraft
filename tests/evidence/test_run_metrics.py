"""Slice 7 — run metrics are measurement-only and carry the batching signal."""

from __future__ import annotations

from mergecraft.evidence.run_packet import _run_metrics
from mergecraft.evidence.trajectory import ToolCallRecord, TrajectoryRecord
from mergecraft.mcp.tool_state import init_tool_state

_DIFF = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,1 +1,2 @@
 one
+two
"""


class _Ctx:
    def __init__(self, state):
        self.tool_state = state


def _call(sequence: int, tool: str, intent: str, *, duration_ms: int = 0) -> ToolCallRecord:
    return ToolCallRecord(
        sequence=sequence,
        tool=tool,
        signature=f"{tool}:{sequence}",
        intent=intent,  # type: ignore[arg-type]  # — test helper uses the documented Intent set
        ok=True,
        duration_ms=duration_ms,
    )


def test_run_metrics_counts_calls_read_turns_and_phases() -> None:
    state = init_tool_state(owner="acme", name="demo", dir="/repo")
    state.phase_elapsed_s = {"setup": 4.0, "agent": 120.0, "publish": 3.0}
    trajectory = TrajectoryRecord(
        tool_calls=[
            _call(1, "shell", "read"),
            _call(2, "shell", "read"),
            _call(3, "run_analyzers", "verify", duration_ms=2500),
            _call(4, "verify_agent_findings", "verify", duration_ms=500),
            _call(5, "shell", "read"),
        ],
        files_read=["src/app.py", "src/other.py"],
        read_coverage=True,
    )

    metrics = _run_metrics(_Ctx(state), trajectory=trajectory, diff_text=_DIFF)

    assert metrics.tool_calls == 5
    assert metrics.read_tool_calls == 3
    assert metrics.read_tool_turns == 2, "adjacent reads collapse into one turn"
    assert metrics.distinct_files_read == 2
    assert metrics.diff_added_lines == 1
    assert metrics.diff_deleted_lines == 0
    assert metrics.phase_elapsed_s["analyzers"] == 2.5
    assert metrics.phase_elapsed_s["judge"] == 0.5
    assert metrics.phase_elapsed_s["setup"] == 4.0


def test_run_metrics_carries_the_idle_diagnostic() -> None:
    state = init_tool_state(owner="acme", name="demo", dir="/repo")
    state.agent_diagnostic = {"diagnostic": "codex stalled — no model event for 900s"}

    metrics = _run_metrics(_Ctx(state), trajectory=TrajectoryRecord(), diff_text=_DIFF)

    assert metrics.agent_diagnostic == "codex stalled — no model event for 900s"


def test_record_renders_review_cost_and_the_stall() -> None:
    from types import SimpleNamespace

    from mergecraft.evidence.packet import RunMetrics
    from mergecraft.findings.ledger import render_deterministic_review_block

    metrics = RunMetrics(
        tool_calls=9,
        read_tool_calls=4,
        read_tool_turns=2,
        distinct_files_read=3,
        diff_lines=120,
        diff_added_lines=20,
        diff_deleted_lines=3,
        phase_elapsed_s={"setup": 2.0, "agent": 90.0, "publish": 1.0},
        agent_diagnostic="codex stalled — no model event for 900s",
    )
    packet = SimpleNamespace(
        files_changed=[],
        findings=[],
        run_health=None,
        deterministic_checks=[],
        decision=None,
        self_assessment=None,
        agent=None,
        run_metrics=metrics,
        change_id="acme/demo#7",
    )

    text = render_deterministic_review_block(packet=packet)

    assert "- **Review cost:** 9 tool calls · 3 files read · 120 diff lines" in text
    assert "setup 2s, agent 90s, publish 1s" in text
    assert "**Agent stall:** codex stalled" in text


# ── #1075 — honest phase timing on agent-published records ──────────────────


def test_run_metrics_reports_agent_elapsed_so_far_when_unstamped() -> None:
    """The dispatch-end stamp is invisible mid-dispatch; elapsed-so-far is honest."""
    state = init_tool_state(owner="acme", name="demo", dir="/repo")
    state.agent_started_monotonic = 100.0

    metrics = _run_metrics(
        _Ctx(state), trajectory=TrajectoryRecord(), diff_text=_DIFF, now=lambda: 175.5
    )

    assert metrics.phase_elapsed_s["agent"] == 75.5


def test_run_metrics_agent_falls_back_to_zero_without_a_dispatch_marker() -> None:
    """A run that never dispatched an agent has no elapsed to derive."""
    state = init_tool_state(owner="acme", name="demo", dir="/repo")

    metrics = _run_metrics(
        _Ctx(state), trajectory=TrajectoryRecord(), diff_text=_DIFF, now=lambda: 175.5
    )

    assert metrics.phase_elapsed_s["agent"] == 0.0


def test_run_metrics_keeps_a_real_agent_stamp_over_elapsed_so_far() -> None:
    """The end-of-run record renders the final stamp, not a mid-dispatch estimate."""
    state = init_tool_state(owner="acme", name="demo", dir="/repo")
    state.agent_started_monotonic = 100.0
    state.phase_elapsed_s = {"agent": 416.0}

    metrics = _run_metrics(
        _Ctx(state), trajectory=TrajectoryRecord(), diff_text=_DIFF, now=lambda: 999.0
    )

    assert metrics.phase_elapsed_s["agent"] == 416.0


def test_run_metrics_omits_publish_until_the_run_stamps_it() -> None:
    """``publish`` is stamped after its own record renders — unstamped means omitted."""
    state = init_tool_state(owner="acme", name="demo", dir="/repo")

    metrics = _run_metrics(_Ctx(state), trajectory=TrajectoryRecord(), diff_text=_DIFF)

    assert "publish" not in metrics.phase_elapsed_s
    assert metrics.phase_elapsed_s["setup"] == 0.0

    state.phase_elapsed_s = {"publish": 0.4}
    stamped = _run_metrics(_Ctx(state), trajectory=TrajectoryRecord(), diff_text=_DIFF)

    assert stamped.phase_elapsed_s["publish"] == 0.4


def test_record_renders_sub_second_phases_honestly() -> None:
    """Sub-second work must not read as ``0s``; an absent publish stays absent."""
    from types import SimpleNamespace

    from mergecraft.evidence.packet import RunMetrics
    from mergecraft.findings.ledger import render_deterministic_review_block

    metrics = RunMetrics(
        tool_calls=22,
        read_tool_calls=9,
        read_tool_turns=4,
        distinct_files_read=3,
        diff_lines=161,
        diff_added_lines=100,
        diff_deleted_lines=61,
        phase_elapsed_s={"setup": 0.0, "analyzers": 0.124, "agent": 416.0, "judge": 0.02},
    )
    packet = SimpleNamespace(
        files_changed=[],
        findings=[],
        run_health=None,
        deterministic_checks=[],
        decision=None,
        self_assessment=None,
        agent=None,
        run_metrics=metrics,
        change_id="acme/demo#7",
    )

    text = render_deterministic_review_block(packet=packet)

    assert "setup 0s, analyzers 0.1s, agent 416s, judge <0.1s" in text
    assert "publish" not in text
