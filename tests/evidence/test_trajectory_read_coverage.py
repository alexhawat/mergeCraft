"""RS1.4 — trajectory read-coverage gating (RS2, F10 bounded)."""

from __future__ import annotations

import pytest

from mergecraft.evidence.trajectory import (
    ExternalTraceRef,
    ToolCallRecord,
    build_trajectory_record,
)
from mergecraft.mcp.tool_state import init_tool_state


def _empty_external_trace() -> ExternalTraceRef:
    return ExternalTraceRef(source="mergecraft.tracing", event_count=0, tool_calls=[])


def _read_external_trace() -> ExternalTraceRef:
    return ExternalTraceRef(
        source="mergecraft.tracing",
        event_count=1,
        tool_calls=[
            ToolCallRecord(
                sequence=1,
                tool="Read",
                signature="Read:1",
                intent="read",
                ok=True,
                paths=["docs/REVIEW-DOCTRINE.md"],
            )
        ],
    )


@pytest.mark.xfail(reason="green after RS2: empty external trace is not coverage", strict=False)
def test_external_trace_with_no_reads_is_not_read_coverage() -> None:
    state = init_tool_state(owner="acme", name="demo", dir="/tmp/demo")
    record = build_trajectory_record(state, external_trace=_empty_external_trace())
    assert record.files_read == []
    assert record.read_coverage is False


def test_external_trace_with_reads_is_read_coverage() -> None:
    state = init_tool_state(owner="acme", name="demo", dir="/tmp/demo")
    record = build_trajectory_record(state, external_trace=_read_external_trace())
    assert record.files_read == ["docs/REVIEW-DOCTRINE.md"]
    assert record.read_coverage is True


def test_mcp_observed_reads_are_still_read_coverage() -> None:
    from mergecraft.evidence.trajectory import record_tool_call

    state = init_tool_state(owner="acme", name="demo", dir="/tmp/demo")
    record_tool_call(
        state,
        tool="shell",
        arguments={"command": "cat src/app.py"},
        ok=True,
        outcome_ok=True,
    )
    record = build_trajectory_record(state)
    assert record.read_coverage is True
