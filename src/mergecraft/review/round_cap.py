"""Configurable review-round cap with a reconsider finding (#1166).

Counts only mergeCraft-authored prior reviews (same rule as
:func:`mergecraft.mcp.checkout.review_round_index`). Exceeding the cap injects
one blocking finding; it never auto-approves a PR.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from mergecraft.analyzers.finding import make_finding

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding
    from mergecraft.config.settings import RepoSettings

ROUND_CAP_RULE_ID: Final[str] = "review-round-cap-exceeded"
ROUND_CAP_TOOL: Final[str] = "review-round-cap"


def max_review_rounds(settings: RepoSettings | None) -> int:
    """Resolved cap; ``0`` disables the cap."""
    if settings is None:
        return 3
    return max(0, int(settings.review.max_review_rounds))


def review_round_cap_exceeded(*, round_index: int, cap: int) -> bool:
    """True when this run's 1-based round index is past ``cap``."""
    if cap <= 0:
        return False
    return round_index > cap


def round_cap_finding(*, round_index: int, cap: int) -> Finding:
    """Blocking finding asking the author to reconsider the approach."""
    return make_finding(
        tool=ROUND_CAP_TOOL,
        rule_id=ROUND_CAP_RULE_ID,
        category="Maintainability & Code Quality",
        severity="Major",
        confidence="certain",
        message=(
            f"This pull request is on review round {round_index} (cap {cap}). "
            "Step back and reconsider the approach — incremental fixes are unlikely "
            "to converge. Post a short plan or split the work before pushing more commits."
        ),
        path="",
        start_line=1,
        end_line=1,
        source="trajectory",
        scope="change",
        evidence=[f"review_round_index={round_index}", f"max_review_rounds={cap}"],
        remediation=(
            "Pause feature iteration on this branch: explain the revised approach in a "
            "comment, or open a smaller follow-up PR."
        ),
        introduced_by_pr="true",
    )


def round_cap_findings_for_run(
    *,
    round_index: int,
    settings: RepoSettings | None,
    already_posted: bool,
) -> list[Finding]:
    """Return at most one cap finding when exceeded and not yet posted this run."""
    cap = max_review_rounds(settings)
    if already_posted or not review_round_cap_exceeded(round_index=round_index, cap=cap):
        return []
    return [round_cap_finding(round_index=round_index, cap=cap)]


__all__ = [
    "ROUND_CAP_RULE_ID",
    "max_review_rounds",
    "review_round_cap_exceeded",
    "round_cap_finding",
    "round_cap_findings_for_run",
]
