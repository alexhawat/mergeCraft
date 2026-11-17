"""Authorize one native review-comment event and read its bounded thread context.

Module: mergecraft.action.discuss_thread
Depends: mergecraft.config.trust_policy, mergecraft.review.authorship, mergecraft.utils.github

Exports:
    Classes:
        DiscussContextError — Incomplete or malformed GitHub evidence.
        DiscussionMention — Bound repository, pull request, thread and author identifiers.
        DiscussionContext — Original finding, diff hunk and earlier replies.
    Functions:
        bind_discussion_mention — Bind an eligible native event to Actions metadata.
        authorize_discussion — Verify current pull request and actor permissions.
        read_discussion_thread — Read an eligible thread and detect replies to this mention.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from mergecraft.config.trust_policy import is_fork_pull_request
from mergecraft.findings.materiality import DISMISSAL_REASON_CODES
from mergecraft.findings.threads import positive_database_id
from mergecraft.review.authorship import is_mergecraft_authored
from mergecraft.review_resolution import is_publisher_login
from mergecraft.utils.github import paginate_github_list_pages
from mergecraft.utils.learnings import TRUSTED_AUTHOR_ASSOCIATIONS

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mergecraft.scm.protocol import ScmProvider

_LOGIN = re.compile(r"[A-Za-z0-9-]{1,39}")
_REPOSITORY = re.compile(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9_.-]{1,100}")
_MENTION = re.compile(r"(?<![\w@/.-])@mergecraft(?![\w/-])", re.IGNORECASE)
_DISMISS = re.compile(r"@mergecraft[ \t]+dismiss[ \t]+([a-z_]+)", re.IGNORECASE)
_WRITE_PERMISSIONS = frozenset({"write", "maintain", "admin"})


class DiscussContextError(RuntimeError):
    """GitHub returned insufficient evidence to safely answer the mention."""


@dataclass(frozen=True, slots=True)
class DiscussionMention:
    """An Action invocation bound to a particular GitHub repository, PR and comment."""

    repository: str
    repository_id: int
    pull_number: int
    comment_id: int
    root_id: int
    login: str
    user_id: int
    body: str

    @property
    def pull_api_path(self) -> str:
        """Return the REST path scoped to this repository and pull request."""
        return f"/repos/{self.repository}/pulls/{self.pull_number}"

    @property
    def reply_marker(self) -> str:
        """Mark a reply to this exact mention for replay detection."""
        return f"<!-- mergecraft-discuss:v1:{self.comment_id} -->"


@dataclass(frozen=True, slots=True)
class DiscussionContext:
    """The original finding, anchor, and messages earlier than the mention."""

    finding: str
    path: str
    diff_hunk: str
    prior_replies: tuple[str, ...]


def _record(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _same_repository(record: object, repository: str, repository_id: int) -> bool:
    details = _record(record)
    name = details.get("full_name")
    return (
        isinstance(name, str)
        and name.casefold() == repository.casefold()
        and positive_database_id(details.get("id")) == repository_id
    )


def _same_repo_pull(pull: dict[str, Any], repository: str, repository_id: int) -> bool:
    return (
        not is_fork_pull_request({"pull_request": pull})
        and _same_repository(_record(pull.get("base")).get("repo"), repository, repository_id)
        and _same_repository(_record(pull.get("head")).get("repo"), repository, repository_id)
    )


def _is_actor(user: object, login: str, user_id: int) -> bool:
    row = _record(user)
    actual_login = row.get("login")
    return (
        row.get("type") == "User"
        and isinstance(actual_login, str)
        and actual_login.casefold() == login.casefold()
        and positive_database_id(row.get("id")) == user_id
    )


def bind_discussion_mention(
    event: dict[str, Any], environment: Mapping[str, str]
) -> DiscussionMention | None:
    """Bind an explicit created reply by an eligible human to Actions metadata."""
    repository = environment.get("GITHUB_REPOSITORY", "")
    login = environment.get("GITHUB_ACTOR", "")
    if event.get("action") != "created" or not _REPOSITORY.fullmatch(repository):
        return None
    if repository.partition("/")[2] in {".", ".."} or not _LOGIN.fullmatch(login):
        return None
    user_id = positive_database_id(environment.get("GITHUB_ACTOR_ID"))
    comment = _record(event.get("comment"))
    if (
        user_id is None
        or not _is_actor(event.get("sender"), login, user_id)
        or not _is_actor(comment.get("user"), login, user_id)
        or comment.get("author_association") not in tuple(TRUSTED_AUTHOR_ASSOCIATIONS)
    ):
        return None
    body = comment.get("body")
    if not isinstance(body, str) or not _MENTION.search(body):
        return None
    command = _DISMISS.fullmatch(body.partition("\n")[0].strip())
    if command is not None and command[1].lower() in DISMISSAL_REASON_CODES:
        return None
    event_repo = _record(event.get("repository"))
    repo_id = positive_database_id(event_repo.get("id"))
    pull = _record(event.get("pull_request"))
    pull_number = positive_database_id(pull.get("number"))
    comment_id = positive_database_id(comment.get("id"))
    root_id = positive_database_id(comment.get("in_reply_to_id"))
    if (
        repo_id is None
        or pull_number is None
        or comment_id is None
        or root_id is None
        or root_id == comment_id
        or not _same_repository(event_repo, repository, repo_id)
        or not _same_repo_pull(pull, repository, repo_id)
    ):
        return None
    return DiscussionMention(
        repository, repo_id, pull_number, comment_id, root_id, login, user_id, body
    )


async def authorize_discussion(scm: ScmProvider, mention: DiscussionMention) -> bool:
    """Verify that the bound PR is open, same-repository and the asker can write."""
    pull = _record(await scm.get(mention.pull_api_path))
    if (
        positive_database_id(pull.get("number")) != mention.pull_number
        or pull.get("state") != "open"
        or not _same_repo_pull(pull, mention.repository, mention.repository_id)
    ):
        return False
    try:
        permission = _record(
            await scm.get(f"/repos/{mention.repository}/collaborators/{mention.login}/permission")
        )
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            return False
        raise
    level = permission.get("permission")
    return (
        isinstance(level, str)
        and level in _WRITE_PERMISSIONS
        and _is_actor(permission.get("user"), mention.login, mention.user_id)
    )


async def read_discussion_thread(
    scm: ScmProvider, mention: DiscussionMention, publishers: frozenset[str]
) -> DiscussionContext | None:
    """Read one genuine mergeCraft thread unless the mention is stale or answered."""

    async def page(number: int) -> dict[str, Any]:
        return {
            "comments": await scm.get(
                f"{mention.pull_api_path}/comments",
                params={"page": number, "per_page": 100, "sort": "created", "direction": "asc"},
            )
        }

    listing = await paginate_github_list_pages(page, item_key="comments")
    if listing.incomplete:
        msg = "Discuss could not read the complete pull request comment list."
        raise DiscussContextError(msg)
    comments: dict[int, dict[str, Any]] = {}
    for row in listing.items:
        comment_id = positive_database_id(row.get("id"))
        if comment_id is None or comment_id in comments:
            msg = "Discuss received malformed pull request comments."
            raise DiscussContextError(msg)
        comments[comment_id] = row

    root = comments.get(mention.root_id, {})
    trigger = comments.get(mention.comment_id, {})
    if (
        root.get("in_reply_to_id") is not None
        or not is_mergecraft_authored(root, publishers=publishers)
        or positive_database_id(trigger.get("in_reply_to_id")) != mention.root_id
        or not _is_actor(trigger.get("user"), mention.login, mention.user_id)
        or trigger.get("author_association") not in tuple(TRUSTED_AUTHOR_ASSOCIATIONS)
        or trigger.get("body") != mention.body
    ):
        return None

    context: list[str] = []
    before_mention = True
    for comment_id, row in comments.items():
        if comment_id == mention.comment_id:
            before_mention = False
            continue
        if positive_database_id(row.get("in_reply_to_id")) != mention.root_id:
            continue
        body = row.get("body")
        if not isinstance(body, str):
            msg = "Discuss received a malformed reply in the requested thread."
            raise DiscussContextError(msg)
        publisher = is_publisher_login(_record(row.get("user")).get("login"), publishers)
        if publisher and body.rstrip().endswith(f"\n{mention.reply_marker}"):
            return None
        if before_mention:
            context.append(body)

    finding, path, hunk = root.get("body"), root.get("path"), root.get("diff_hunk")
    if not isinstance(finding, str) or not isinstance(path, str) or not isinstance(hunk, str):
        msg = "Discuss could not read the original finding and diff hunk."
        raise DiscussContextError(msg)
    return DiscussionContext(finding, path, hunk, tuple(context))
