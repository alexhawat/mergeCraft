"""Deterministic human outcomes for published mergeCraft findings (#1165).

Classifies each mergeCraft-originated review thread into fixed / rejected /
intentional / ignored from GitHub thread state, human replies, and merge state.
Advisory only — never feeds :func:`mergecraft.agents.gates.decide_approval`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from mergecraft.review_resolution import (
    effective_publishers,
    finding_fingerprints_in,
    is_publisher_authored_comment,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

FindingOutcomeKind = Literal["fixed", "rejected", "intentional", "ignored", "unknown"]

_WONT_FIX_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(won'?t fix|wontfix|by design|intentional|not a bug|false positive|false-positive)\b",
    re.IGNORECASE,
)
_REJECT_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(wrong|incorrect|not valid|disagree|invalid finding|not an issue)\b",
    re.IGNORECASE,
)


class FindingOutcomeRow(BaseModel):
    """Outcome for one published finding (thread)."""

    model_config = ConfigDict(extra="forbid")

    fingerprint: str
    thread_id: str
    path: str = ""
    line: int | None = None
    outcome: FindingOutcomeKind
    reason: str = ""


class FindingOutcomeReport(BaseModel):
    """Aggregate advisory outcome rates."""

    model_config = ConfigDict(extra="forbid")

    pull_number: int
    merged: bool
    rows: list[FindingOutcomeRow] = Field(default_factory=list)
    incomplete: bool = False

    def rates(self) -> dict[FindingOutcomeKind, float]:
        """Fraction of classified rows per outcome (excludes unknown)."""
        counts: dict[FindingOutcomeKind, int] = {
            "fixed": 0,
            "rejected": 0,
            "intentional": 0,
            "ignored": 0,
            "unknown": 0,
        }
        for row in self.rows:
            counts[row.outcome] += 1
        classified = sum(counts[k] for k in ("fixed", "rejected", "intentional", "ignored"))
        if classified == 0:
            return {key: 0.0 for key in counts}
        return {key: counts[key] / classified for key in counts if key != "unknown"}


def _human_replies(comments: Sequence[dict[str, Any]], publishers: frozenset[str]) -> list[str]:
    bodies: list[str] = []
    for comment in comments:
        if is_publisher_authored_comment(comment, publishers):
            continue
        login = str(comment.get("author") or comment.get("user", {}).get("login") or "")
        if login.endswith("[bot]"):
            continue
        bodies.append(str(comment.get("body") or ""))
    return bodies


def classify_thread_outcome(
    thread: dict[str, Any],
    *,
    publishers: frozenset[str],
    merged: bool,
) -> tuple[FindingOutcomeKind, str]:
    """Classify one review thread without LLM calls."""
    comments = list(thread.get("comments") or [])
    if not comments:
        return "unknown", "empty thread"
    root = comments[0]
    if not is_publisher_authored_comment(root, publishers):
        return "unknown", "not mergeCraft-originated"
    fps = finding_fingerprints_in(str(root.get("body") or ""))
    if not fps:
        return "unknown", "no finding fingerprint"
    if thread.get("isResolved") or thread.get("resolved"):
        return "fixed", "thread resolved"
    if thread.get("isOutdated") or thread.get("outdated"):
        return "fixed", "thread outdated"
    human = _human_replies(comments, publishers)
    combined = "\n".join(human)
    if combined and _WONT_FIX_RE.search(combined):
        return "intentional", "human marked won't-fix / by design"
    if combined and _REJECT_RE.search(combined):
        return "rejected", "human rejected the finding"
    if merged:
        return "ignored", "merged with thread still open"
    return "ignored", "open thread, PR not merged yet"


def classify_pull_request_outcomes(
    *,
    pull_number: int,
    threads: Sequence[dict[str, Any]],
    publishers: frozenset[str],
    merged: bool,
    incomplete: bool = False,
) -> FindingOutcomeReport:
    """Build an outcome report for all mergeCraft threads on a PR."""
    effective = effective_publishers(publishers)
    rows: list[FindingOutcomeRow] = []
    for thread in threads:
        comments = list(thread.get("comments") or [])
        if not comments:
            continue
        root = comments[0]
        if not is_publisher_authored_comment(root, effective):
            continue
        fps = finding_fingerprints_in(str(root.get("body") or ""))
        if not fps:
            continue
        outcome, reason = classify_thread_outcome(thread, publishers=effective, merged=merged)
        fp = next(iter(fps))
        rows.append(
            FindingOutcomeRow(
                fingerprint=fp,
                thread_id=str(thread.get("id") or thread.get("graphqlId") or ""),
                path=str(root.get("path") or ""),
                line=root.get("line") if isinstance(root.get("line"), int) else None,
                outcome=outcome,
                reason=reason,
            )
        )
    return FindingOutcomeReport(
        pull_number=pull_number,
        merged=merged,
        rows=rows,
        incomplete=incomplete,
    )


def flywheel_candidate_from_outcome(
    row: FindingOutcomeRow,
    *,
    case_id: str,
    run_id: str,
    author_login: str,
    pr_number: int | None,
) -> dict[str, Any] | None:
    """Map rejected/intentional outcomes to flywheel ingest payloads (provenance required)."""
    if row.outcome not in {"rejected", "intentional"}:
        return None
    return {
        "case_id": case_id,
        "title": f"Human {row.outcome} finding {row.fingerprint[:8]}",
        "category": "false_positive" if row.outcome == "rejected" else "intentional_accept",
        "failure_mode": row.outcome,
        "expected_finding": row.path or row.fingerprint,
        "expected_decision": "neutral",
        "provenance": "agent-seeded",
        "run_id": run_id,
        "author_login": author_login,
        "pr_number": pr_number,
        "body": row.reason,
    }


__all__ = [
    "FindingOutcomeKind",
    "FindingOutcomeReport",
    "FindingOutcomeRow",
    "classify_pull_request_outcomes",
    "classify_thread_outcome",
    "flywheel_candidate_from_outcome",
]
