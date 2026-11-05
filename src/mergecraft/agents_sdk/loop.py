"""Review / fix loop helpers for Agents SDK integrations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mergecraft.agents_sdk.guardrails import filter_guarded_findings, sanitize_review_output
from mergecraft.agents_sdk.types import ReviewFindingsReport

if TYPE_CHECKING:
    from agents import Agent


ApplyFixCallback = Callable[[ReviewFindingsReport], Awaitable[None]]
RunReviewCallback = Callable[[], Awaitable[ReviewFindingsReport]]


@dataclass(frozen=True, slots=True)
class ReviewLoopResult:
    """Outcome of ``run_review_loop``."""

    rounds: int
    final_report: ReviewFindingsReport
    guardrail_violations: tuple[str, ...]


async def run_review_loop(
    *,
    run_review: RunReviewCallback,
    apply_fixes: ApplyFixCallback | None = None,
    allowed_paths: frozenset[str],
    max_rounds: int = 3,
) -> ReviewLoopResult:
    """Review, optionally apply fixes, and repeat until clean or ``max_rounds``."""
    if max_rounds < 1:
        msg = "max_rounds must be >= 1"
        raise ValueError(msg)

    report = ReviewFindingsReport()
    violations: list[str] = []
    round_index = 0
    while round_index < max_rounds:
        round_index += 1
        report = await run_review()
        filtered, blocked = filter_guarded_findings(report, allowed_paths=allowed_paths)
        violations.extend(blocked)
        report = filtered
        if not report.blocking_findings():
            break
        if apply_fixes is None or round_index >= max_rounds:
            break
        await apply_fixes(report)
    return ReviewLoopResult(
        rounds=round_index,
        final_report=report,
        guardrail_violations=tuple(violations),
    )


def review_agent_as_tool(
    agent: Agent[Any],
    *,
    allowed_paths: frozenset[str],
    tool_name: str = "mergecraft_review",
) -> Any:
    """Expose ``review_agent`` as an Agents SDK tool for a coding agent."""
    from agents import function_tool

    @function_tool(name_override=tool_name)
    async def _review_tool() -> ReviewFindingsReport:
        from agents import Runner

        result = await Runner.run(agent, input="Review the current workspace change.")
        if not isinstance(result.final_output, ReviewFindingsReport):
            msg = "review agent did not return ReviewFindingsReport"
            raise TypeError(msg)
        return sanitize_review_output(result.final_output, allowed_paths=allowed_paths)

    return _review_tool


__all__ = ["ReviewLoopResult", "review_agent_as_tool", "run_review_loop"]
