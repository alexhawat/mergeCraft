"""Deterministic human outcomes for published mergeCraft findings (#1165).

Classifies each mergeCraft-originated review thread into fixed / rejected /
intentional / ignored / stale from GitHub thread state, human replies, and merge state.
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
    from collections.abc import Iterable, Sequence

FindingOutcomeKind = Literal["fixed", "rejected", "intentional", "ignored", "stale", "unknown"]

_INTENTIONAL_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(won'?t fix|wontfix|by design|intentional)\b",
    re.IGNORECASE,
)
_REJECT_RE: Final[re.Pattern[str]] = re.compile(
    r"\b("
    r"wrong|incorrect|not valid|disagree|invalid finding|not an issue|"
    r"false positive|false-positive|not a bug"
    r")\b",
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
            "stale": 0,
            "unknown": 0,
        }
        for row in self.rows:
            counts[row.outcome] += 1
        classified = sum(
            counts[k] for k in ("fixed", "rejected", "intentional", "ignored", "stale")
        )
        if classified == 0:
            return {key: 0.0 for key in counts}
        return {key: counts[key] / classified for key in counts if key != "unknown"}


_CLASSIFIED_KINDS: Final[tuple[FindingOutcomeKind, ...]] = (
    "fixed",
    "rejected",
    "intentional",
    "ignored",
    "stale",
)


class FindingOutcomeSummary(BaseModel):
    """Advisory outcome rates across several pull requests, with a clean-PR check.

    ``known_clean_pulls`` are pull requests a human has already established carry
    nothing worth flagging (the PRs behind the golden ``clean`` cases, or any
    operator-declared clean change). Every mergeCraft finding published on one is
    a false positive by construction, whatever a human later did with its thread,
    so they are counted on their own (``clean_pull_findings``) instead of being
    left to the reply classifier. The summary is evidence only: nothing here is
    read by :func:`mergecraft.agents.gates.decide_approval`.
    """

    model_config = ConfigDict(extra="forbid")

    advisory: Literal[True] = True
    pulls: list[int] = Field(default_factory=list)
    counts: dict[FindingOutcomeKind, int] = Field(default_factory=dict)
    rates: dict[FindingOutcomeKind, float] = Field(default_factory=dict)
    known_clean_pulls: list[int] = Field(default_factory=list)
    clean_pull_findings: int = 0
    clean_pull_findings_per_pull: float | None = None
    incomplete_pulls: list[int] = Field(default_factory=list)


def summarize_outcomes(
    reports: Sequence[FindingOutcomeReport],
    *,
    known_clean_pulls: Iterable[int] = (),
) -> FindingOutcomeSummary:
    """Aggregate per-PR reports into advisory rates and the known-clean FP check.

    Rates are over classified rows (``unknown`` excluded) on every PR, so a clean
    PR's findings still count toward their reply-derived outcome as well. The
    clean-PR check divides by the number of known-clean PRs that were actually
    reported, so a PR that was declared clean but not fetched cannot dilute it.
    """
    counts: dict[FindingOutcomeKind, int] = dict.fromkeys((*_CLASSIFIED_KINDS, "unknown"), 0)
    clean = frozenset(known_clean_pulls)
    clean_reported: list[int] = []
    clean_findings = 0
    for report in reports:
        for row in report.rows:
            counts[row.outcome] += 1
        if report.pull_number in clean:
            clean_reported.append(report.pull_number)
            clean_findings += len(report.rows)
    classified = sum(counts[kind] for kind in _CLASSIFIED_KINDS)
    rates: dict[FindingOutcomeKind, float] = {
        kind: (counts[kind] / classified if classified else 0.0) for kind in _CLASSIFIED_KINDS
    }
    return FindingOutcomeSummary(
        pulls=[report.pull_number for report in reports],
        counts=counts,
        rates=rates,
        known_clean_pulls=sorted(clean_reported),
        clean_pull_findings=clean_findings,
        clean_pull_findings_per_pull=(
            clean_findings / len(clean_reported) if clean_reported else None
        ),
        incomplete_pulls=[report.pull_number for report in reports if report.incomplete],
    )


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
        # Outdated only means the anchored line changed; it does not prove the
        # finding was addressed, so it must not inflate the "fixed" rate (#1251).
        return "stale", "thread outdated (anchor changed; not confirmed fixed)"
    human = _human_replies(comments, publishers)
    combined = "\n".join(human)
    if combined and _REJECT_RE.search(combined):
        return "rejected", "human rejected the finding"
    if combined and _INTENTIONAL_RE.search(combined):
        return "intentional", "human marked won't-fix / by design"
    if merged:
        return "ignored", "merged with thread still open"
    return "unknown", "open thread, PR not merged yet"


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
                thread_id=str(
                    thread.get("threadId") or thread.get("id") or thread.get("graphqlId") or ""
                ),
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
    "FindingOutcomeSummary",
    "classify_pull_request_outcomes",
    "classify_thread_outcome",
    "flywheel_candidate_from_outcome",
    "summarize_outcomes",
]
