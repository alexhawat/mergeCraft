"""The network half of finding carryover: read threads, file what survives.

Split from :mod:`mergecraft.findings.select` so the selection rules stay pure
and testable without a GitHub client. This layer adds exactly two concerns the
pure layer cannot have: reading the pull request, and not filing the same
finding twice.

Idempotence is carried by the carryover key — the pull request number plus the
finding fingerprint — not by run bookkeeping. Every issue this module files
embeds that key in its body, and every run reads the keys back out of
already-filed issues first. Re-running the sweep on the same pull request is
therefore a no-op, which is what makes it safe to attach to a workflow trigger
that can fire more than once, while the same finding reintroduced by a *later*
pull request still files: that is a regression, not a duplicate.

Exports:
    CarryoverOutcome: What a sweep filed, and what it could not.
    CarryoverPlan: What a sweep would file, and what it would skip.
    FiledIssue: One issue the sweep created.
    apply_carryover: File the planned issues.
    plan_carryover: Decide what to file, without writing anything.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import httpx
from loguru import logger
from pydantic import BaseModel, Field

from mergecraft.findings.select import (
    DEFAULT_LABEL,
    CarryoverFinding,
    carryover_findings,
    carryover_key,
    carryover_keys_in,
    issue_body,
    issue_title,
)
from mergecraft.findings.threads import fetch_review_threads

if TYPE_CHECKING:
    from mergecraft.findings.lifecycle import LifecycleRecord
    from mergecraft.utils.github import GitHubClient

_ISSUE_PAGE_SIZE: Final[int] = 100
_MAX_ISSUE_PAGES: Final[int] = 20
_LABEL_EXISTS: Final[int] = 422

LABEL_COLOR: Final[str] = "d4c5f9"
LABEL_DESCRIPTION: Final[str] = "Review finding that outlived its pull request"


class FiledIssue(BaseModel):
    """One issue the sweep created.

    Attributes:
        number: Issue number GitHub assigned.
        url: Issue HTML URL.
        title: Title the sweep rendered.
        fingerprint: Finding identity now recorded on the issue.
    """

    number: int
    url: str
    title: str
    fingerprint: str


class FailedIssue(BaseModel):
    """One issue the sweep could not create.

    Attributes:
        title: Title the sweep tried to file.
        fingerprint: Finding identity that stayed unfiled.
        error: Stringified transport or API error.
    """

    title: str
    fingerprint: str
    error: str


class CarryoverOutcome(BaseModel):
    """The result of a write pass.

    Attributes:
        pull_number: The pull request swept.
        filed: Issues created, in plan order.
        failed: Findings that could not be filed. Non-empty means the sweep did
            not do its job, and the caller must not report success.
    """

    pull_number: int
    filed: list[FiledIssue] = Field(default_factory=list)
    failed: list[FailedIssue] = Field(default_factory=list)


class CarryoverPlan(BaseModel):
    """What a sweep of one pull request would do.

    Attributes:
        pull_number: The pull request swept.
        to_file: Findings with no issue yet.
        already_filed: Findings skipped because an issue already carries them.
        truncated: Whether the pull request had more threads than one page holds.
    """

    pull_number: int
    to_file: list[CarryoverFinding] = Field(default_factory=list)
    already_filed: list[CarryoverFinding] = Field(default_factory=list)
    truncated: bool = False


async def filed_carryover_keys(
    github: GitHubClient,
    owner: str,
    repo: str,
    *,
    label: str = DEFAULT_LABEL,
) -> frozenset[str]:
    """Return every carryover key already recorded on a filed issue.

    Reads the label directly rather than the search index: search is eventually
    consistent, and a stale miss here files a duplicate issue.

    Args:
        github: Authenticated client.
        owner: Repository owner.
        repo: Repository name.
        label: Label the sweep applies to the issues it files.

    Returns:
        Keys found in open and closed carryover issues. A closed issue still
        counts — that finding was dealt with on that pull request, not lost.
    """
    seen: set[str] = set()
    for page in range(1, _MAX_ISSUE_PAGES + 1):
        issues = await github.list_issues(
            owner,
            repo,
            params={
                "labels": label,
                "state": "all",
                "per_page": _ISSUE_PAGE_SIZE,
                "page": page,
            },
        )
        for issue in issues:
            seen |= carryover_keys_in(str(issue.get("body") or ""))
        if len(issues) < _ISSUE_PAGE_SIZE:
            break
    return frozenset(seen)


async def plan_carryover(
    github: GitHubClient,
    owner: str,
    repo: str,
    pull_number: int,
    *,
    label: str = DEFAULT_LABEL,
    include_resolved: bool = False,
    include_answered: bool = False,
    ledger_records: list[LifecycleRecord] | None = None,
) -> CarryoverPlan:
    """Decide which findings to file for ``pull_number`` without writing anything.

    Args:
        github: Authenticated client.
        owner: Repository owner.
        repo: Repository name.
        pull_number: Pull request to sweep.
        label: Label used to find issues already filed.
        include_resolved: Carry over threads the author resolved.
        include_answered: Carry over threads a human replied to.
        ledger_records: Open-PR ledger rows — fingerprints already tracked there
            are not filed while the pull request is open (D5).

    Returns:
        A :class:`CarryoverPlan`; ``to_file`` is empty when nothing survives or
        everything was already filed.
    """
    from mergecraft.scm.github import GitHubScmAdapter

    page = await fetch_review_threads(
        GitHubScmAdapter(github), owner, repo, pull_number, include_resolved=include_resolved
    )
    if page.truncated:
        logger.warning(
            "carryover: PR #{} has {} review threads, more than one page — "
            "some findings were not examined",
            pull_number,
            page.total_count,
        )

    findings = carryover_findings(
        page.threads,
        include_resolved=include_resolved,
        include_answered=include_answered,
    )
    known = (
        await filed_carryover_keys(github, owner, repo, label=label) if findings else frozenset()
    )
    ledger_fps = {record.fingerprint for record in (ledger_records or [])}

    to_file: list[CarryoverFinding] = []
    already: list[CarryoverFinding] = []
    planned: set[str] = set()
    for finding in findings:
        if finding.fingerprint in ledger_fps:
            already.append(finding)
            continue
        key = carryover_key(pull_number=pull_number, fingerprint=finding.fingerprint)
        # `planned` also guards the within-run case: two threads whose text and
        # path match normalize to one fingerprint, and one issue is the point.
        if key in known or key in planned:
            already.append(finding)
            continue
        planned.add(key)
        to_file.append(finding)

    return CarryoverPlan(
        pull_number=pull_number,
        to_file=to_file,
        already_filed=already,
        truncated=page.truncated,
    )


async def _ensure_label(github: GitHubClient, owner: str, repo: str, label: str) -> None:
    """Create ``label`` when missing, so dedupe can rely on finding it later.

    GitHub silently drops unknown labels for actors without push access. A
    dropped label would break the next run's dedupe read and file duplicates
    forever, so the label is created up front rather than assumed.
    """
    try:
        await github.create_label(
            owner,
            repo,
            name=label,
            color=LABEL_COLOR,
            description=LABEL_DESCRIPTION,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != _LABEL_EXISTS:
            raise
        logger.debug("carryover: label {} already exists", label)


async def apply_carryover(
    github: GitHubClient,
    owner: str,
    repo: str,
    plan: CarryoverPlan,
    *,
    label: str = DEFAULT_LABEL,
) -> CarryoverOutcome:
    """File one issue per finding in ``plan.to_file``.

    Refuses to write a plan built from a truncated read. Filing the visible
    findings and exiting clean would leave the rest behind while making the
    sweep look complete, and the closing event that triggered it does not fire
    again to correct that.

    Args:
        github: Authenticated client.
        owner: Repository owner.
        repo: Repository name.
        plan: Plan produced by :func:`plan_carryover`.
        label: Label applied to each filed issue.

    Returns:
        A :class:`CarryoverOutcome`. One failure does not strand the rest —
        every remaining finding is still attempted — but each failure is
        recorded so the caller can exit nonzero instead of reporting success.

    Raises:
        ValueError: The plan is truncated, so filing it would silently drop
            findings the read never saw.
    """
    if plan.truncated:
        msg = (
            f"refusing to file a partial sweep: PR #{plan.pull_number} has more "
            "review threads than one page holds, so some findings were never read"
        )
        raise ValueError(msg)
    if not plan.to_file:
        return CarryoverOutcome(pull_number=plan.pull_number)
    await _ensure_label(github, owner, repo, label)

    filed: list[FiledIssue] = []
    failed: list[FailedIssue] = []
    for finding in plan.to_file:
        title = issue_title(finding, pull_number=plan.pull_number)
        try:
            issue = await github.create_issue(
                owner,
                repo,
                title=title,
                body=issue_body(finding, pull_number=plan.pull_number),
                labels=[label],
            )
        except httpx.HTTPError as exc:
            logger.warning("carryover: could not file {!r} — {}", title, exc)
            failed.append(FailedIssue(title=title, fingerprint=finding.fingerprint, error=str(exc)))
            continue
        filed.append(
            FiledIssue(
                number=int(issue.get("number") or 0),
                url=str(issue.get("html_url") or ""),
                title=title,
                fingerprint=finding.fingerprint,
            )
        )
    return CarryoverOutcome(pull_number=plan.pull_number, filed=filed, failed=failed)


__all__ = [
    "LABEL_COLOR",
    "LABEL_DESCRIPTION",
    "CarryoverOutcome",
    "CarryoverPlan",
    "FailedIssue",
    "FiledIssue",
    "apply_carryover",
    "filed_carryover_keys",
    "plan_carryover",
]
