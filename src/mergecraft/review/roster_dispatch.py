"""Reviewer roster dispatch batches and harness instructions (D15)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.agents.registry import AgentRole

if TYPE_CHECKING:
    from mergecraft.agents.registry import Registry


def reviewer_dispatch_batches(registry: Registry) -> tuple[tuple[str, ...], ...]:
    """Return reviewer ``agent_id`` batches per dispatch level (D15)."""
    levels = registry.resolve_role_levels(AgentRole.reviewer)
    return tuple(tuple(binding.agent_id for binding in level) for level in levels)


def flatten_dispatch_batches(batches: tuple[tuple[str, ...], ...]) -> tuple[str, ...]:
    """Return every reviewer id in dispatch-level order."""
    return tuple(agent_id for batch in batches for agent_id in batch)


def format_reviewer_dispatch_instructions(
    batches: tuple[tuple[str, ...], ...],
) -> str:
    """Build orchestrator-facing instructions for level-by-level reviewer dispatch."""
    if not batches:
        return ""
    if len(batches) == 1 and len(batches[0]) <= 1:
        return ""

    lines = [
        "Multi-reviewer roster dispatch (D15) — dispatch reviewers level by level:",
    ]
    for index, batch in enumerate(batches):
        joined = ", ".join(batch)
        if index == 0:
            lines.append(f"- Level {index} (parallel): {joined}")
        else:
            lines.append(f"- Level {index} (after level {index - 1} completes): {joined}")
    lines.extend(
        [
            "",
            "Do NOT dispatch reviewers from level N+1 until every reviewer at "
            "level N has finished or failed. Within one level, dispatch all "
            "reviewers in parallel (one assistant turn with multiple Task blocks).",
            "After each reviewer subagent completes successfully, call "
            "`record_reviewer_dispatch_run` with that reviewer's ``agent_id`` and "
            "its findings before submit_review_verdict.",
            "A failed dependency does not cancel later levels — call "
            "`record_reviewer_dispatch_error` for each reviewer that produced no "
            "findings before submit_review_verdict.",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "flatten_dispatch_batches",
    "format_reviewer_dispatch_instructions",
    "reviewer_dispatch_batches",
]
