"""MCP review phase forward-only machine."""

from __future__ import annotations

import pytest

from mergecraft.mcp.review_phase_machine import (
    OPERATIONAL_REVIEW_PHASES,
    advance_review_phase,
    current_review_phase,
    reset_review_phase_on_scope_invalidate,
)
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.mcp.verdict import ReviewPhase


def test_operational_phases_exclude_dead_values() -> None:
    assert ReviewPhase.COLLECT_EVIDENCE not in OPERATIONAL_REVIEW_PHASES
    assert ReviewPhase.POLICY not in OPERATIONAL_REVIEW_PHASES


def test_empty_phase_is_init() -> None:
    ts = init_tool_state(owner="o", name="n", dir="/tmp/x")
    assert current_review_phase(ts) is ReviewPhase.INIT


def test_advance_is_forward_only() -> None:
    ts = init_tool_state(owner="o", name="n", dir="/tmp/x")
    advance_review_phase(ts, ReviewPhase.PUBLISH)
    advance_review_phase(ts, ReviewPhase.SUBMIT)
    assert ts.review_phase == ReviewPhase.PUBLISH.value


def test_reset_on_invalidate() -> None:
    ts = init_tool_state(owner="o", name="n", dir="/tmp/x")
    advance_review_phase(ts, ReviewPhase.SUBMIT)
    reset_review_phase_on_scope_invalidate(ts)
    assert current_review_phase(ts) is ReviewPhase.INIT


def test_non_operational_phase_rejected() -> None:
    ts = init_tool_state(owner="o", name="n", dir="/tmp/x")
    with pytest.raises(ValueError, match="not operational"):
        advance_review_phase(ts, ReviewPhase.COLLECT_EVIDENCE)
