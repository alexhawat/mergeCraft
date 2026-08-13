"""The network half of finding carryover: read threads, file what survives.

Split from :mod:`mergecraft.findings.select` so the selection rules stay pure
and testable without a GitHub client. This layer adds exactly two concerns the
pure layer cannot have: reading the pull request, and not filing the same
finding twice.

Idempotence is carried by the finding fingerprint, not by run bookkeeping. Every
issue this module files embeds the marker in its body, and every run reads the
markers back out of already-filed issues first. Re-running the sweep on the same
pull request is therefore a no-op, which is what makes it safe to attach to a
workflow trigger that can fire more than once.

Exports:
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
    issue_body,
    issue_title,
)
from mergecraft.findings.threads import fetch_review_threads
from mergecraft.review_resolution import finding_fingerprints_in

if TYPE_CHECKING:
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


async def filed_fingerprints(
    github: GitHubClient,
    owner: str,
    repo: str,
    *,
    label: str = DEFAULT_LABEL,
) -> frozenset[str]:
    """Return every finding fingerprint already recorded on a carryover issue.

    Reads the label directly rather than the search index: search is eventually
    consistent, and a stale miss here files a duplicate issue.

    Args:
        github: Authenticated client.
        owner: Repository owner.
        repo: Repository name.
        label: Label the sweep applies to the issues it files.

    Returns:
        Fingerprints found in open and closed carryover issues. A closed issue
        still counts — the finding was dealt with, not lost.
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
            seen |= finding_fingerprints_in(str(issue.get("body") or ""))
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

    Returns:
        A :class:`CarryoverPlan`; ``to_file`` is empty when nothing survives or
        everything was already filed.
    """
    page = await fetch_review_threads(
        github, owner, repo, pull_number, include_resolved=include_resolved
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
    known = await filed_fingerprints(github, owner, repo, label=label) if findings else frozenset()

    to_file: list[CarryoverFinding] = []
    already: list[CarryoverFinding] = []
    planned: set[str] = set()
    for finding in findings:
        # `planned` also guards the within-run case: two threads whose text and
        # path match normalize to one fingerprint, and one issue is the point.
        if finding.fingerprint in known or finding.fingerprint in planned:
            already.append(finding)
            continue
        planned.add(finding.fingerprint)
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
) -> list[FiledIssue]:
    """File one issue per finding in ``plan.to_file``.

    Args:
        github: Authenticated client.
        owner: Repository owner.
        repo: Repository name.
        plan: Plan produced by :func:`plan_carryover`.
        label: Label applied to each filed issue.

    Returns:
        The issues created, in plan order. One failure does not strand the rest;
        failures are logged and omitted from the return value.
    """
    if not plan.to_file:
        return []
    await _ensure_label(github, owner, repo, label)

    filed: list[FiledIssue] = []
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
            continue
        filed.append(
            FiledIssue(
                number=int(issue.get("number") or 0),
                url=str(issue.get("html_url") or ""),
                title=title,
                fingerprint=finding.fingerprint,
            )
        )
    return filed


__all__ = [
    "LABEL_COLOR",
    "LABEL_DESCRIPTION",
    "CarryoverPlan",
    "FiledIssue",
    "apply_carryover",
    "filed_fingerprints",
    "plan_carryover",
]
