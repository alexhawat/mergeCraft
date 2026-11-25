"""Resolve mergeCraft's fixed finding threads after an incremental review.

Module: mergecraft.mcp.review_threads
Depends: mergecraft.mcp.{inline_anchors,review_comments,tool_state}, mergecraft.review_resolution

Exports:
    Functions:
        resolve_fixed_finding_threads — Close eligible threads whose findings are gone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.mcp.inline_anchors import build_inline_anchor_index
from mergecraft.mcp.review_comments import fetch_review_thread_page, resolve_review_thread
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.review_resolution import resolvable_thread_ids
from mergecraft.types import INCREMENTAL_REVIEW_MODE

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

__all__ = ["resolve_fixed_finding_threads"]


def _incremental_changed_lines(primary: Any) -> dict[str, list[range]] | None:
    """New-file line ranges the incremental diff touched, per path.

    Read from the RIGHT side of each hunk of the patch since the last reviewed
    commit (inclusive bounds become half-open ranges). A thread GitHub marks
    outdated qualifies on that flag alone, so the LEFT side adds nothing but
    old-file coordinates that could match an unrelated current line.

    Returns ``None`` when the diff cannot be read: without it no line is known
    to have changed, and retirement must not guess.
    """
    diff_path = getattr(primary, "incremental_diff_path", None)
    if not diff_path:
        return None
    from pathlib import Path

    try:
        diff_text = Path(str(diff_path)).read_text(encoding="utf-8")
    except OSError as err:
        logger.info("finding resolution: incremental diff unreadable, resolving nothing: {}", err)
        return None
    index = build_inline_anchor_index(diff_text)
    return {
        path: [range(start, end + 1) for start, end in sides.get("RIGHT", [])]
        for path, sides in index.hunk_ranges.items()
    }


async def resolve_fixed_finding_threads(
    ctx: ToolContext, *, pull_number: int, still_raised: frozenset[str]
) -> int:
    """Close threads for findings the new commits fixed (C4).

    Runs only on a re-review that knows which paths moved since the last reviewed
    commit. A thread is closed when every comment in it is mergeCraft's (marker
    and an expected-publisher author), its anchored line falls in a hunk of the
    incremental diff or GitHub marks it outdated, and none of its findings is
    still raised anywhere in this run's submission. The expected-publisher set
    comes from the run's authorship rule only; the login the review was just
    posted as is never added to it. Everything here is advisory: a failure logs
    and the review still stands.
    """
    if ctx.tool_state.selected_mode != INCREMENTAL_REVIEW_MODE:
        return 0
    primary = primary_repo_state(ctx.tool_state)
    if not primary.incremental_changed_paths:
        return 0
    changed_lines = _incremental_changed_lines(primary)
    if changed_lines is None:
        return 0
    from mergecraft.review.authorship import resolve_publisher_logins

    publishers = await resolve_publisher_logins(ctx)
    try:
        page = await fetch_review_thread_page(ctx, pull_number) if publishers else None
    except Exception as err:  # advisory cleanup; never fails a posted review
        logger.info("finding resolution: listing review threads soft-failed: {}", err)
        return 0
    threads = page.threads if page is not None else []
    if page is not None and page.incomplete:
        logger.info(
            "finding resolution: the thread listing for PR #{} is incomplete, so threads "
            "that were not read in full stay open",
            pull_number,
        )
    targets = resolvable_thread_ids(
        threads,
        current_fingerprints=still_raised,
        changed_lines=changed_lines,
        publishers=publishers,
    )
    resolved = 0
    for thread_id in targets:
        try:
            is_resolved = await resolve_review_thread(ctx, thread_id)
        except Exception as err:  # one bad thread must not stop the rest
            logger.info("finding resolution: resolving thread {} soft-failed: {}", thread_id, err)
            continue
        if not is_resolved:
            logger.info("finding resolution: GitHub did not confirm thread {} resolved", thread_id)
            continue
        resolved += 1
    if resolved:
        logger.info(
            "resolved {} review thread(s) on PR #{} whose findings are gone from the new commits",
            resolved,
            pull_number,
        )
    return resolved
