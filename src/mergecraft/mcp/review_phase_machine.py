"""Forward-only ``ReviewPhase`` transitions for MCP review runs (#SM3)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from mergecraft.mcp.verdict import ReviewPhase, stamp_review_phase_on_active_span

if TYPE_CHECKING:
    from mergecraft.mcp.tool_state import ToolState

# Values that are part of the live MCP path today (engine uses a separate 4-stage map).
OPERATIONAL_REVIEW_PHASES: Final[tuple[ReviewPhase, ...]] = (
    ReviewPhase.INIT,
    ReviewPhase.ESTABLISH_SCOPE,
    ReviewPhase.SUBMIT,
    ReviewPhase.PUBLISH,
    ReviewPhase.COMPLETE,
)

_PHASE_ORDER: Final[dict[ReviewPhase, int]] = {
    phase: index for index, phase in enumerate(OPERATIONAL_REVIEW_PHASES)
}


def current_review_phase(tool_state: ToolState) -> ReviewPhase:
    raw = tool_state.review_phase
    if not raw:
        return ReviewPhase.INIT
    return ReviewPhase(raw)


def advance_review_phase(tool_state: ToolState, phase: ReviewPhase) -> None:
    """Advance ``review_phase`` forward only; no-op when already at or past ``phase``."""
    if phase not in _PHASE_ORDER:
        msg = f"review phase {phase.value!r} is not operational in the MCP lifecycle"
        raise ValueError(msg)
    current = current_review_phase(tool_state)
    if _PHASE_ORDER[phase] < _PHASE_ORDER.get(current, 0):
        return
    tool_state.review_phase = phase.value
    stamp_review_phase_on_active_span(phase)


def reset_review_phase_on_scope_invalidate(tool_state: ToolState) -> None:
    """Checkout invalidation returns the run to INIT."""
    tool_state.review_phase = ReviewPhase.INIT.value
    stamp_review_phase_on_active_span(ReviewPhase.INIT)


__all__ = [
    "OPERATIONAL_REVIEW_PHASES",
    "advance_review_phase",
    "current_review_phase",
    "reset_review_phase_on_scope_invalidate",
]
