"""Skip agent dispatch when this exact head SHA already has a trusted review (#1490)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.action.review_policy import _is_completed_review
from mergecraft.findings.ledger import DETERMINISTIC_RECORD_MARKER, REVIEW_BODY_MARKER

if TYPE_CHECKING:
    from mergecraft.action.review_state import RunContext

SAME_HEAD_RECOGNIZER = "sameHeadSha"
_HEAD_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def trusted_completed_review_on_head(
    reviews: list[dict[str, Any]], head_sha: str
) -> dict[str, Any] | None:
    """Newest mergeCraft formal review on ``head_sha`` with a terminal success record."""
    if not _HEAD_SHA_RE.fullmatch(head_sha or ""):
        return None
    target = head_sha.casefold()
    for review in reversed(reviews):
        commit = review.get("commit_id")
        if not isinstance(commit, str) or commit.casefold() != target:
            continue
        if not _is_completed_review(review):
            continue
        return dict(review)
    return None


def prior_review_pointer(review: dict[str, Any]) -> str:
    """Human-readable pointer for the run record."""
    url = str(review.get("html_url") or "").strip()
    commit = str(review.get("commit_id") or "")[:12]
    if url:
        return f"prior review on `{commit}` ({url})"
    return f"prior review on `{commit}`"


async def evaluate_same_head_skip(
    ctx: RunContext, *, head_sha: str, pull_number: int
) -> str | None:
    """Return a skip reason when ``head_sha`` already has a trusted completed review."""
    from mergecraft.mcp.checkout import list_mergecraft_reviews

    assert ctx.tool_context is not None
    reviews = await list_mergecraft_reviews(ctx.tool_context, pull_number=pull_number)
    prior = trusted_completed_review_on_head(reviews, head_sha)
    if prior is None:
        return None
    reason = (
        "This head SHA already has a trusted mergeCraft review; "
        f"reusing {prior_review_pointer(prior)} instead of dispatching the agent again."
    )
    logger.info("same_head_review: skip — {}", reason)
    return reason


def review_looks_spoofed(review: dict[str, Any]) -> bool:
    """Reject bodies that mimic our marker without a full deterministic record."""
    body = str(review.get("body") or "").lstrip()
    if not body.startswith(DETERMINISTIC_RECORD_MARKER):
        return True
    return REVIEW_BODY_MARKER not in body


__all__ = [
    "SAME_HEAD_RECOGNIZER",
    "evaluate_same_head_skip",
    "prior_review_pointer",
    "review_looks_spoofed",
    "trusted_completed_review_on_head",
]
