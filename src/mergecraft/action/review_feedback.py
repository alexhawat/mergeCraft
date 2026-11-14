"""Read persisted GitHub feedback and explicit base-branch approvals for a review.

Exports:
    collect_review_feedback — collect advisory proposals and run-scoped approvals.
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger

from mergecraft.findings.materiality import DISMISSAL_REASON_CODES
from mergecraft.findings.threads import fetch_review_threads
from mergecraft.memory.feedback import (
    APPROVED_FEEDBACK_PATH,
    MAX_APPROVAL_BYTES,
    MAX_HISTORY_PULLS,
    ApprovedFeedback,
    FeedbackHistory,
    FeedbackReport,
    is_feedback_path,
    parse_approved_feedback,
)
from mergecraft.review.authorship import resolve_publisher_logins
from mergecraft.review_resolution import (
    effective_publishers,
    finding_fingerprints_in,
    is_publisher_authored_comment,
    is_publisher_login,
)
from mergecraft.utils.learnings import TRUSTED_AUTHOR_ASSOCIATIONS

if TYPE_CHECKING:
    from mergecraft.action.review_state import RunContext
    from mergecraft.scm.protocol import ScmProvider

_BASE_TIMEOUT_S = 5.0
_PUBLISHER_TIMEOUT_S = 2.0
_HISTORY_TIMEOUT_S = 12.0
_REACTION_PAGE_SIZE = 50
_SHA = re.compile(r"[0-9a-f]{40}")
_FINGERPRINT = re.compile(r"[0-9a-f]{6,64}")
_LOGIN = re.compile(r"[A-Za-z0-9-]{1,39}")
_DISMISSAL = re.compile(r"@mergecraft[ \t]+dismiss[ \t]+([a-z_]+)[ \t]*", re.IGNORECASE)
_WRITERS = frozenset({"write", "maintain", "admin"})

_REVIEW_FEEDBACK_QUERY = """
query($owner: String!, $repo: String!, $number: Int!, $baseOid: GitObjectID!,
      $ref: String!, $path: String!, $limit: Int!) {
  repository(owner: $owner, name: $repo) {
    nameWithOwner
    defaultBranchRef { name }
    pullRequest(number: $number) { number headRefOid baseRefOid baseRefName }
    object(oid: $baseOid) {
      ... on Commit {
        oid
        file(path: $path) {
          mode size
          object { ... on Blob { text isBinary isTruncated } }
        }
      }
    }
    pullRequests(first: $limit, baseRefName: $ref, orderBy: {field: CREATED_AT, direction: DESC}) {
      totalCount
      pageInfo { hasNextPage }
      nodes { number }
    }
  }
}
"""


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _positive_id(value: object) -> int | None:
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,18}", value):
        value = int(value)
    return value if type(value) is int and value > 0 else None


def _read_approval(
    blob_commit: object, *, base_sha: str, repository: str
) -> tuple[ApprovedFeedback, ...]:
    commit = _mapping(blob_commit)
    entry = _mapping(commit.get("file"))
    blob = _mapping(entry.get("object"))
    size, text = entry.get("size"), blob.get("text")
    if commit.get("oid") != base_sha or not entry:
        return ()
    if (
        entry.get("mode") not in {0o100644, 0o100755}
        or type(size) is not int
        or not 0 < size <= MAX_APPROVAL_BYTES
        or not isinstance(text, str)
        or len(text.encode()) != size
        or blob.get("isBinary") is not False
        or blob.get("isTruncated") is not False
    ):
        logger.warning("» review feedback: the base approval file is not a bounded text file")
        return ()
    approved = parse_approved_feedback(text, repository)
    if not approved:
        logger.debug("» review feedback: the base approval file has no valid entries")
    return approved


def _recent_pulls(connection: object, *, current: int) -> tuple[list[int], bool, bool]:
    page = _mapping(connection)
    nodes, count = page.get("nodes"), page.get("totalCount")
    more = _mapping(page.get("pageInfo")).get("hasNextPage")
    if not isinstance(nodes, list) or type(count) is not int or not isinstance(more, bool):
        return [current], False, False
    numbers = [_positive_id(_mapping(node).get("number")) for node in nodes]
    if (
        count < len(nodes)
        or None in numbers
        or len(numbers) != len(set(numbers))
        or (count > len(nodes)) != more
    ):
        return [current], False, False
    pulls = [current, *(number for number in numbers if number is not None and number != current)]
    limited = more or len(pulls) > MAX_HISTORY_PULLS
    return pulls[:MAX_HISTORY_PULLS], limited, True


class _GitHubFeedback:
    def __init__(self, scm: ScmProvider, owner: str, repo: str, publishers: frozenset[str]) -> None:
        self.scm = scm
        self.owner = owner
        self.repo = repo
        self.publishers = publishers
        self.permissions: dict[tuple[str, int], bool] = {}
        self.incomplete = False

    async def _actor_can_write(self, actor: object, *, id_key: str) -> bool:
        user = _mapping(actor)
        login, actor_id = user.get("login"), _positive_id(user.get(id_key))
        if not isinstance(login, str) or not _LOGIN.fullmatch(login) or actor_id is None:
            return False
        if is_publisher_login(login, self.publishers):
            return False
        key = (login.casefold(), actor_id)
        if key not in self.permissions:
            try:
                data = _mapping(
                    await self.scm.get(
                        f"/repos/{self.owner}/{self.repo}/collaborators/{login}/permission"
                    )
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
                self.permissions[key] = False
                return False
            returned = _mapping(data.get("user"))
            # GitHub supplies the actor identity in both APIs. A login alone can be reused.
            permission = data.get("permission")
            if permission in ("read", "triage", "none"):
                self.permissions[key] = False
            elif (
                isinstance(permission, str)
                and permission in _WRITERS
                and returned.get("type") == "User"
                and str(returned.get("login") or "").casefold() == key[0]
                and _positive_id(returned.get("id")) == actor_id
            ):
                self.permissions[key] = True
            else:
                self.incomplete = True
                return False
        return self.permissions[key]

    async def _negative_reaction(self, root: dict[str, Any], comment: int) -> bool:
        count = _mapping(root.get("negativeReactions")).get("totalCount")
        if type(count) is not int or not 0 <= count <= _REACTION_PAGE_SIZE:
            self.incomplete = True
            return False
        if not count:
            return False
        reactions = await self.scm.get(
            f"/repos/{self.owner}/{self.repo}/pulls/comments/{comment}/reactions",
            params={"content": "-1", "per_page": _REACTION_PAGE_SIZE},
        )
        if (
            not isinstance(reactions, list)
            or len(reactions) != count
            or any(
                not isinstance(reaction, dict) or reaction.get("content") != "-1"
                for reaction in reactions
            )
        ):
            self.incomplete = True
            return False
        for reaction in reactions:
            if await self._actor_can_write(reaction.get("user"), id_key="id"):
                return True
        return False

    async def _reasons(
        self, thread: dict[str, Any], comments: list[dict[str, Any]], comment: int
    ) -> set[str]:
        dismissals = set()
        for reply in comments[1:]:
            body = reply.get("body")
            if (
                reply.get("state") != "SUBMITTED"
                or reply.get("authorAssociation") not in TRUSTED_AUTHOR_ASSOCIATIONS
                or not isinstance(body, str)
            ):
                continue
            first_line = body.partition("\n")[0].strip()
            command = _DISMISSAL.fullmatch(first_line)
            if (
                command is not None
                and command[1].lower() in DISMISSAL_REASON_CODES
                and await self._actor_can_write(reply.get("feedbackActor"), id_key="databaseId")
            ):
                dismissals.add(command[1].lower())
        if dismissals:
            return dismissals
        if thread.get("isResolved") is True and await self._actor_can_write(
            thread.get("resolvedBy"), id_key="databaseId"
        ):
            return {"thread_resolved"}
        if await self._negative_reaction(comments[0], comment):
            return {"thumbs_down"}
        return set()

    async def collect_pull(self, history: FeedbackHistory, pull: int) -> bool:
        page = await fetch_review_threads(
            self.scm, self.owner, self.repo, pull, include_resolved=True, include_feedback=True
        )
        if page.incomplete:
            return False
        self.incomplete = False
        observed: list[tuple[str, str, int, set[str]]] = []
        for thread in page.threads:
            comments = thread["comments"]
            if not comments:
                continue
            root = comments[0]
            if (
                "replyTo" not in root
                or root["replyTo"] is not None
                or root.get("state") != "SUBMITTED"
                or not is_publisher_authored_comment(root, self.publishers)
            ):
                continue
            path, comment = root.get("path"), _positive_id(root.get("fullDatabaseId"))
            fingerprints = finding_fingerprints_in(str(root.get("body") or ""))
            if (
                not isinstance(path, str)
                or not is_feedback_path(path)
                or comment is None
                or len(fingerprints) != 1
            ):
                continue
            fingerprint = next(iter(fingerprints))
            if not _FINGERPRINT.fullmatch(fingerprint):
                continue
            reasons = await self._reasons(thread, comments, comment)
            if reasons:
                observed.append((fingerprint, path, comment, reasons))
        if self.incomplete:
            return False
        for fingerprint, path, comment, reasons in observed:
            history.add(
                fingerprint=fingerprint, path=path, pull=pull, comment=comment, reasons=reasons
            )
        return True


async def _collect_history(
    source: _GitHubFeedback, connection: object, report: FeedbackReport, *, current: int
) -> None:
    pulls, report.history_limited, available = _recent_pulls(connection, current=current)
    history = FeedbackHistory()
    remaining = pulls.copy()
    try:
        async with asyncio.timeout(_HISTORY_TIMEOUT_S):
            for pull in pulls:
                try:
                    complete = await source.collect_pull(history, pull)
                except Exception as exc:
                    logger.warning(
                        "» review feedback: PR #{} could not be read ({})", pull, type(exc).__name__
                    )
                    complete = False
                (report.examined_pulls if complete else report.unread_pulls).append(pull)
                remaining.remove(pull)
    except TimeoutError:
        report.unread_pulls.extend(remaining)
    report.status = "complete" if available and not report.unread_pulls else "partial"
    report.staged, report.proposals_limited = history.proposals(report.repository)


async def collect_review_feedback(
    ctx: RunContext,
) -> tuple[FeedbackReport | None, tuple[ApprovedFeedback, ...]]:
    """Bind to GitHub's default branch before trusting approvals or harvesting history."""
    if ctx.tool_context is None:
        return None, ()
    tool = ctx.tool_context
    pull = _mapping((ctx.gh_event or {}).get("pull_request"))
    number = _positive_id(pull.get("number"))
    base, head = _mapping(pull.get("base")), _mapping(pull.get("head"))
    base_sha, head_sha, ref = base.get("sha"), head.get("sha"), base.get("ref")
    if not isinstance(base_sha, str) or not isinstance(head_sha, str):
        return None, ()
    if (
        number is None
        or not isinstance(ref, str)
        or not ref
        or not (_SHA.fullmatch(base_sha) and _SHA.fullmatch(head_sha))
    ):
        return None, ()
    owner, repo = tool.repo.owner, tool.repo.name
    repository = f"{owner}/{repo}"
    report = FeedbackReport(repository=repository, status="unavailable")
    try:
        async with asyncio.timeout(_BASE_TIMEOUT_S):
            data = await tool.scm.graphql(
                _REVIEW_FEEDBACK_QUERY,
                {
                    "owner": owner,
                    "repo": repo,
                    "number": number,
                    "baseOid": base_sha,
                    "ref": ref,
                    "path": APPROVED_FEEDBACK_PATH,
                    "limit": MAX_HISTORY_PULLS,
                },
            )
    except Exception as exc:
        logger.debug("» review feedback: base snapshot unavailable ({})", type(exc).__name__)
        return report, ()
    snapshot = _mapping(data.get("repository"))
    bound = _mapping(snapshot.get("pullRequest"))
    if (
        str(snapshot.get("nameWithOwner") or "").casefold() != repository.casefold()
        or _mapping(snapshot.get("defaultBranchRef")).get("name") != ref
        or bound.get("number") != number
        or bound.get("headRefOid") != head_sha
        or bound.get("baseRefOid") != base_sha
        or bound.get("baseRefName") != ref
    ):
        return report, ()
    approved = _read_approval(snapshot.get("object"), base_sha=base_sha, repository=repository)
    try:
        async with asyncio.timeout(_PUBLISHER_TIMEOUT_S):
            publishers = effective_publishers(await resolve_publisher_logins(tool))
    except TimeoutError:
        return report, approved
    if not publishers:
        return report, approved
    source = _GitHubFeedback(tool.scm, owner, repo, publishers)
    await _collect_history(source, snapshot.get("pullRequests"), report, current=number)
    approved_ids = {entry.id for entry in approved}
    report.staged = [entry for entry in report.staged if entry.id not in approved_ids]
    return report, approved
