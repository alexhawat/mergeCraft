"""Monotonic LLM review generation timing for posted review output (#983 task 6)."""

from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass, field

from mergecraft.utils.duration import format_duration

_WALL_TIME_EPSILON_S = 2.0
_WALL_TIME_RATIO_EPSILON = 0.05

_TRACKER: ContextVar[LlmReviewTimingTracker | None] = ContextVar(
    "mergecraft_llm_review_timing",
    default=None,
)


@dataclass(slots=True)
class ReviewerGenerationTiming:
    agent_id: str
    generation_start: float | None = None
    generation_end: float | None = None

    def llm_seconds(self) -> float | None:
        if self.generation_start is None or self.generation_end is None:
            if self.generation_start is not None and self.generation_end is None:
                return max(0.0, time.monotonic() - self.generation_start)
            return None
        return max(0.0, self.generation_end - self.generation_start)


@dataclass
class LlmReviewTimingTracker:
    reviewers: dict[str, ReviewerGenerationTiming] = field(default_factory=dict)
    wall_start: float | None = None
    wall_end: float | None = None

    def note_llm_call_start(self, agent_id: str) -> None:
        key = agent_id.strip() or "reviewer"
        now = time.monotonic()
        if self.wall_start is None:
            self.wall_start = now
        row = self.reviewers.setdefault(key, ReviewerGenerationTiming(agent_id=key))
        if row.generation_start is None:
            row.generation_start = now

    def note_generation_end(self, agent_id: str, *, role: str) -> None:
        if role != "reviewer":
            return
        key = agent_id.strip() or "reviewer"
        now = time.monotonic()
        self.wall_end = now
        row = self.reviewers.setdefault(key, ReviewerGenerationTiming(agent_id=key))
        if row.generation_end is None and row.generation_start is not None:
            row.generation_end = now

    def finalize(self) -> None:
        now = time.monotonic()
        if self.wall_end is None:
            self.wall_end = now
        for row in self.reviewers.values():
            if row.generation_start is not None and row.generation_end is None:
                row.generation_end = now


@dataclass(frozen=True, slots=True)
class LlmReviewTimingSnapshot:
    per_reviewer_seconds: tuple[tuple[str, float], ...]
    total_llm_seconds: float
    wall_seconds: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "per_reviewer": {agent_id: seconds for agent_id, seconds in self.per_reviewer_seconds},
            "total_llm_seconds": self.total_llm_seconds,
            "wall_seconds": self.wall_seconds,
            "line": format_llm_review_timing_line(self),
        }


def bind_llm_review_timing_tracker() -> LlmReviewTimingTracker:
    tracker = LlmReviewTimingTracker()
    _TRACKER.set(tracker)
    return tracker


def get_llm_review_timing_tracker() -> LlmReviewTimingTracker | None:
    return _TRACKER.get()


def clear_llm_review_timing_tracker() -> None:
    _TRACKER.set(None)


def snapshot_llm_review_timing(
    tracker: LlmReviewTimingTracker | None = None,
) -> LlmReviewTimingSnapshot | None:
    active = tracker if tracker is not None else get_llm_review_timing_tracker()
    if active is None:
        return None
    active.finalize()
    rows: list[tuple[str, float]] = []
    for key in sorted(active.reviewers):
        seconds = active.reviewers[key].llm_seconds()
        if seconds is not None and seconds > 0:
            rows.append((key, seconds))
    if not rows and active.wall_start is None:
        return None
    total = sum(seconds for _, seconds in rows)
    wall: float | None = None
    if active.wall_start is not None and active.wall_end is not None:
        wall = max(0.0, active.wall_end - active.wall_start)
    if not rows and wall is not None:
        rows = [("reviewer", wall)]
        total = wall
    if total <= 0 and (wall is None or wall <= 0):
        return None
    return LlmReviewTimingSnapshot(
        per_reviewer_seconds=tuple(rows),
        total_llm_seconds=total,
        wall_seconds=wall,
    )


def _wall_differs_meaningfully(total_llm_seconds: float, wall_seconds: float | None) -> bool:
    if wall_seconds is None:
        return False
    if wall_seconds <= 0:
        return False
    if abs(wall_seconds - total_llm_seconds) <= _WALL_TIME_EPSILON_S:
        return False
    if total_llm_seconds <= 0:
        return True
    ratio_delta = abs(wall_seconds - total_llm_seconds) / total_llm_seconds
    return ratio_delta > _WALL_TIME_RATIO_EPSILON


def format_llm_review_timing_line(snapshot: LlmReviewTimingSnapshot) -> str:
    """Return the operator-facing timing line, e.g. ``⏱ LLM review time: 3m 11s``."""
    total_label = format_duration(snapshot.total_llm_seconds)
    if len(snapshot.per_reviewer_seconds) <= 1:
        line = f"⏱ LLM review time: {total_label}"
    else:
        parts = ", ".join(
            f"{agent_id} {format_duration(seconds)}"
            for agent_id, seconds in snapshot.per_reviewer_seconds
        )
        line = f"⏱ LLM review time: {total_label} total ({parts})"
    if _wall_differs_meaningfully(snapshot.total_llm_seconds, snapshot.wall_seconds):
        wall_label = format_duration(snapshot.wall_seconds or 0.0)
        line = f"{line}; wall {wall_label}"
    return line


def format_llm_review_timing_record(snapshot: LlmReviewTimingSnapshot) -> str:
    """Markdown bullet for the deterministic review record."""
    return f"- {format_llm_review_timing_line(snapshot)}"


def note_llm_call_started(agent_id: str | None = None) -> None:
    tracker = get_llm_review_timing_tracker()
    if tracker is None:
        return
    resolved = (agent_id or "").strip()
    if not resolved:
        from mergecraft.tracing.signals import current_agent_id

        resolved = (current_agent_id() or "").strip()
    if not resolved:
        return
    tracker.note_llm_call_start(resolved)


def note_reviewer_generation_ended(agent_id: str, *, role: str) -> None:
    tracker = get_llm_review_timing_tracker()
    if tracker is not None:
        tracker.note_generation_end(agent_id, role=role)


__all__ = [
    "LlmReviewTimingSnapshot",
    "LlmReviewTimingTracker",
    "ReviewerGenerationTiming",
    "bind_llm_review_timing_tracker",
    "clear_llm_review_timing_tracker",
    "format_llm_review_timing_line",
    "format_llm_review_timing_record",
    "get_llm_review_timing_tracker",
    "note_llm_call_started",
    "note_reviewer_generation_ended",
    "snapshot_llm_review_timing",
]
