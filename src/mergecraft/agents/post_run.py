"""Post-run issue collection / reflection (ported from agents/postRun.ts)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from mergecraft.agents.shared import (
    MAX_POST_RUN_RETRIES,
    AgentResult,
    AgentRunContext,
    PostRunIssues,
    StopHookFailure,
    SummaryStale,
    build_commit_prompt,
    get_git_status,
    has_post_run_issues,
    merge_agent_usage,
)
from mergecraft.modes import NON_COMMITTING_MODES

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mergecraft.mcp.tool_state import ToolState


def get_unsubmitted_review(tool_state: ToolState) -> str | None:
    mode = tool_state.selected_mode
    if not tool_state.had_progress_comment:
        return None
    if mode == "Review":
        return None if tool_state.review else "Review"
    if mode == "IncrementalReview":
        if tool_state.review or tool_state.final_summary_written:
            return None
        return "IncrementalReview"
    return None


MAX_HOOK_OUTPUT_CHARS = 4096


def truncate_hook_output(raw: str) -> str:
    if len(raw) <= MAX_HOOK_OUTPUT_CHARS:
        return raw
    return (
        f"...(truncated, showing last {MAX_HOOK_OUTPUT_CHARS} chars)\n"
        f"{raw[-MAX_HOOK_OUTPUT_CHARS:]}"
    )


def build_stop_hook_prompt(failure: StopHookFailure) -> str:
    return "\n".join(
        [
            f"STOP HOOK FAILED — the repo-configured stop hook exited with code "
            f"{failure.exit_code}. your work is not done until the hook exits cleanly. "
            "address the issue below and push any resulting changes to a pull request.",
            "",
            "```",
            failure.output or "(no output)",
            "```",
        ]
    )


async def _is_summary_unchanged(file_path: str, seed: str) -> bool:
    try:
        current = Path(file_path).read_text(encoding="utf-8")
        return current == seed
    except OSError:
        return False


def build_summary_stale_prompt(file_path: str) -> str:
    return "\n".join(
        [
            f"PR SUMMARY UNTOUCHED — the rolling PR summary file at `{file_path}` is "
            "byte-identical to its seed; this run did not edit it.",
            "",
            "review the diff and update the file in place to reflect what changed in the PR.",
        ]
    )


def build_unsubmitted_review_prompt(mode: str) -> str:
    if mode == "Review":
        return "\n".join(
            [
                "MISSING REVIEW OUTPUT — you selected Review mode but stopped without "
                "calling `create_pull_request_review`.",
                "",
                "call `create_pull_request_review` now with your aggregated review.",
                "",
                "do NOT stop again until `create_pull_request_review` has been called "
                "successfully.",
            ]
        )
    return "\n".join(
        [
            "MISSING REVIEW OUTPUT — you selected IncrementalReview mode but stopped "
            "without calling `create_pull_request_review` or `report_progress`.",
            "",
            "do exactly one of:",
            "- if you have findings: call `create_pull_request_review`",
            "- if no review warranted: call `report_progress` with a short summary",
        ]
    )


async def collect_post_run_issues(
    ctx: AgentRunContext,
    *,
    skip_summary_stale: bool = False,
) -> PostRunIssues:
    issues = PostRunIssues()
    status = get_git_status()
    mode = ctx.tool_state.selected_mode
    if status:
        if mode and mode in NON_COMMITTING_MODES:
            logger.info("dirty-tree gate suppressed: mode `{}` does not commit", mode)
        else:
            issues.dirty_tree = status
    summary_file = ctx.tool_state.summary_file_path
    summary_seed = ctx.tool_state.summary_seed
    if not skip_summary_stale and summary_file and summary_seed is not None:
        if await _is_summary_unchanged(summary_file, summary_seed):
            issues.summary_stale = SummaryStale(file_path=summary_file)
    unsubmitted = get_unsubmitted_review(ctx.tool_state)
    if unsubmitted:
        issues.unsubmitted_review = unsubmitted
    return issues


def build_post_run_prompt(issues: PostRunIssues) -> str:
    parts: list[str] = []
    if issues.stop_hook:
        parts.append(build_stop_hook_prompt(issues.stop_hook))
    if issues.unsubmitted_review:
        parts.append(build_unsubmitted_review_prompt(issues.unsubmitted_review))
    if issues.dirty_tree:
        parts.append(build_commit_prompt(issues.dirty_tree))
    if issues.summary_stale:
        parts.append(build_summary_stale_prompt(issues.summary_stale.file_path))
    return "\n\n---\n\n".join(parts)


def build_reflection_prompt(issues: PostRunIssues) -> str:
    """Prompt for a soft reflection turn after soft gates remain."""
    base = build_post_run_prompt(issues)
    return f"{base}\n\nThis is a reflection turn — address the issues above, then stop."


async def finalize_agent_result(ctx: AgentRunContext, result: AgentResult) -> AgentResult:
    """Terminal hard-fail if stopHook / unsubmittedReview still open."""
    if not result.success:
        return result
    issues = await collect_post_run_issues(ctx, skip_summary_stale=True)
    if issues.unsubmitted_review:
        expected = (
            "create_pull_request_review"
            if issues.unsubmitted_review == "Review"
            else "create_pull_request_review or report_progress"
        )
        return AgentResult(
            success=False,
            output=result.output,
            error=(
                f"post-run gate failed: selected {issues.unsubmitted_review} mode but "
                f"never called {expected}"
            ),
            usage=result.usage,
            metadata=result.metadata,
        )
    return result


async def run_post_run_retry_loop(
    ctx: AgentRunContext,
    *,
    initial: AgentResult,
    resume: Callable[[str], Awaitable[AgentResult]],
) -> AgentResult:
    """Resume the agent up to MAX_POST_RUN_RETRIES while hard/soft gates fail.

    ``resume`` is an async callable ``(prompt: str) -> AgentResult``.
    """
    result = initial
    usage = result.usage
    skip_summary = False
    for attempt in range(MAX_POST_RUN_RETRIES):
        issues = await collect_post_run_issues(ctx, skip_summary_stale=skip_summary)
        if not has_post_run_issues(issues):
            break
        if issues.summary_stale and not (
            issues.stop_hook or issues.dirty_tree or issues.unsubmitted_review
        ):
            # soft gate — nudge once
            skip_summary = True
        prompt = build_post_run_prompt(issues)
        logger.info("post-run retry {}/{}", attempt + 1, MAX_POST_RUN_RETRIES)
        result = await resume(prompt)
        usage = merge_agent_usage(usage, result.usage)
        if not result.success:
            result.usage = usage
            return result
    result.usage = usage
    return await finalize_agent_result(ctx, result)
