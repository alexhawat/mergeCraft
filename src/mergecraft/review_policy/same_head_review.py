"""Skip agent dispatch when this exact head SHA already has requested changes (#1490).

The skip reuses only a blocking verdict. A pass on the same head is reviewed again:
the authenticated review history proves who reviewed the head, but not that the
review still applies (the base can move without the head changing), so it cannot
grant approval. Carrying a pass over needs the re-approval proof instead
(:mod:`mergecraft.reapproval`: a trusted App's check and the review-policy stamp).
Reusing requested changes can only keep a merge blocked, never unblock one.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from mergecraft.action.review_policy import _is_completed_review
from mergecraft.classify.triage import TriageDecision
from mergecraft.utils.github import _default_server_url

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

SAME_HEAD_RECOGNIZER = "sameHeadSha"
_HEAD_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def trusted_completed_review_on_head(
    reviews: list[dict[str, Any]], head_sha: str
) -> dict[str, Any] | None:
    """Find the newest completed review on ``head_sha`` in authenticated history."""
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


async def evaluate_same_head_skip(
    ctx: ToolContext, *, head_sha: str, pull_number: int
) -> TriageDecision | None:
    """Build a skip decision from one read of the authenticated review history."""
    from mergecraft.mcp.checkout import list_mergecraft_reviews

    reviews = await list_mergecraft_reviews(ctx, pull_number=pull_number)
    prior = trusted_completed_review_on_head(reviews, head_sha)
    if prior is None or str(prior.get("state")).upper() != "CHANGES_REQUESTED":
        return None
    review_id = prior.get("id")
    pointer = f"prior review on `{head_sha[:12]}`"
    relied_on: tuple[str, ...] = ()
    if type(review_id) is int and review_id > 0:
        url = (
            f"{_default_server_url()}/{ctx.repo.owner}/{ctx.repo.name}"
            f"/pull/{pull_number}#pullrequestreview-{review_id}"
        )
        pointer += f" ({url})"
        relied_on = (url,)
    reason = (
        "This head SHA already has a trusted mergeCraft review that requested changes; "
        f"reusing {pointer} instead of dispatching the agent again. Push a commit or "
        "dispatch a review to get a new one."
    )
    return TriageDecision(
        tier="skip", recognizer=SAME_HEAD_RECOGNIZER, reason=reason, relied_on_checks=relied_on
    )


__all__ = [
    "SAME_HEAD_RECOGNIZER",
    "evaluate_same_head_skip",
    "trusted_completed_review_on_head",
]
