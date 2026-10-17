"""Review-thread retrieval, shared by the MCP tool and the findings sweep.

The GraphQL document and its normalization live here so that
``get_review_comments`` — the tool the reviewing agent calls mid-run — and
``mergecraft findings`` — the post-merge sweep — read a pull request's threads
through exactly one shape. A second copy of this query would drift, and the two
callers disagreeing about what a thread looks like is precisely the failure the
carryover feature exists to prevent.

Both connections are read through their cursors: ``reviewThreads`` a page at a
time, and each thread's ``comments`` a page at a time, each up to a bounded page
cap. Hitting a cap never truncates silently — the page reports ``incomplete``
and the thread names ``commentsTruncated``, so a caller that must not drop
findings (or close a conversation it only half read) can see it.

Exports:
    ReviewThreadPage: Normalized threads plus the ``incomplete`` signal.
    THREADS_QUERY: The GraphQL document that reads a page of threads.
    THREAD_COMMENTS_QUERY: The GraphQL document that reads more of one thread.
    THREADS_PAGE_SIZE, THREADS_MAX_PAGES: Thread paging bounds.
    COMMENTS_PAGE_SIZE, COMMENTS_MAX_PAGES: Per-thread comment paging bounds.
    fetch_review_threads: Read one pull request's review threads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from loguru import logger

if TYPE_CHECKING:
    from mergecraft.scm.protocol import ScmProvider

# GitHub caps both connections at 100 per page. Both are walked by cursor up to
# these bounds; a pull request past them is reported ``incomplete`` rather than
# silently shortened. A human reply hiding past the cap would otherwise make an
# answered conversation look unanswered, which is how a sweep files an issue
# over somebody's explicit "not an issue".
THREADS_PAGE_SIZE: Final[int] = 100
THREADS_MAX_PAGES: Final[int] = 10
COMMENTS_PAGE_SIZE: Final[int] = 100
COMMENTS_MAX_PAGES: Final[int] = 10

_COMMENT_FIELDS: Final[str] = """
              databaseId
              body
              author { login }
              path
              line
              originalLine
              url
              createdAt
"""

THREADS_QUERY: Final[str] = (
    """
query($owner: String!, $repo: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $cursor) {
        totalCount
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          isOutdated
          comments(first: 100) {
            totalCount
            pageInfo { hasNextPage endCursor }
            nodes {"""
    + _COMMENT_FIELDS
    + """            }
          }
        }
      }
    }
  }
}
"""
)

THREAD_COMMENTS_QUERY: Final[str] = (
    """
query($threadId: ID!, $cursor: String) {
  node(id: $threadId) {
    ... on PullRequestReviewThread {
      comments(first: 100, after: $cursor) {
        totalCount
        pageInfo { hasNextPage endCursor }
        nodes {"""
    + _COMMENT_FIELDS
    + """        }
      }
    }
  }
}
"""
)


@dataclass(slots=True)
class ReviewThreadPage:
    """One page of review threads, in the shape ``get_review_comments`` returns.

    Attributes:
        threads: Normalized threads, already filtered by ``include_resolved``.
        total_count: How many threads the pull request has in total.
        incomplete: Whether some thread, or some of a thread's comments, was
            never read — a page cap was hit, or GitHub reported more than it
            returned. Threads that were read in part carry ``commentsTruncated``.
    """

    threads: list[dict[str, Any]] = field(default_factory=list)
    total_count: int = 0
    incomplete: bool = False

    @property
    def truncated(self) -> bool:
        """Alias of :attr:`incomplete`, kept for callers that predate pagination."""
        return self.incomplete


def _connection(data: Any, *path: str) -> dict[str, Any]:
    """Walk ``data`` down ``path`` and return the mapping there, or ``{}``."""
    node: Any = data
    for key in path:
        node = (node or {}).get(key) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


def _has_next(connection: dict[str, Any]) -> tuple[bool, str | None]:
    info = connection.get("pageInfo")
    if not isinstance(info, dict) or not info.get("hasNextPage"):
        return False, None
    cursor = info.get("endCursor")
    return True, str(cursor) if cursor else None


async def _read_all_comments(
    scm: ScmProvider, thread_id: str, first_page: dict[str, Any]
) -> tuple[list[dict[str, Any]], int, bool]:
    """Return ``(comment nodes, total count, truncated)`` for one thread.

    The first page arrives with the thread; the rest are read by cursor until
    GitHub says there are no more or ``COMMENTS_MAX_PAGES`` is reached.
    ``truncated`` is true when comments exist that were not read.
    """
    nodes = list(first_page.get("nodes") or [])
    total = int(first_page.get("totalCount") or len(nodes))
    more, cursor = _has_next(first_page)
    pages = 1
    while more and cursor and pages < COMMENTS_MAX_PAGES:
        data = await scm.graphql(THREAD_COMMENTS_QUERY, {"threadId": thread_id, "cursor": cursor})
        page = _connection(data, "node", "comments")
        batch = list(page.get("nodes") or [])
        if not batch:
            break
        nodes.extend(batch)
        pages += 1
        more, cursor = _has_next(page)
    truncated = total > len(nodes) or more
    if truncated:
        logger.warning(
            "review thread {}: read {} of {} comments (page cap {}); the thread is incomplete",
            thread_id,
            len(nodes),
            total,
            COMMENTS_MAX_PAGES,
        )
    return nodes, total, truncated


async def fetch_review_threads(
    scm: ScmProvider,
    owner: str,
    repo: str,
    pull_number: int,
    *,
    include_resolved: bool = False,
) -> ReviewThreadPage:
    """Return a pull request's review threads, normalized for every caller.

    Threads are read page by page (``THREADS_MAX_PAGES`` pages of
    ``THREADS_PAGE_SIZE``), and each thread's comments page by page
    (``COMMENTS_MAX_PAGES``). Reaching a cap is reported, never hidden.

    Args:
        scm: SCM provider used for the GraphQL call.
        owner: Repository owner.
        repo: Repository name.
        pull_number: Pull request number.
        include_resolved: Keep threads GitHub reports as resolved.

    Returns:
        A :class:`ReviewThreadPage`. ``threads`` is empty when the pull request
        has none, or when every thread was filtered out as resolved;
        ``incomplete`` is true when anything was left unread.
    """
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_count = 0
    cursor: str | None = None
    more = True
    pages = 0
    while more and pages < THREADS_MAX_PAGES:
        data = await scm.graphql(
            THREADS_QUERY,
            {"owner": owner, "repo": repo, "number": pull_number, "cursor": cursor},
        )
        connection = _connection(data, "repository", "pullRequest", "reviewThreads")
        batch = list(connection.get("nodes") or [])
        pages += 1
        total_count = max(total_count, int(connection.get("totalCount") or 0))
        for node in batch:
            node_id = str(node.get("id") or "")
            if node_id and node_id in seen:
                continue
            seen.add(node_id)
            nodes.append(node)
        more, cursor = _has_next(connection)
        if not batch or not cursor:
            break
    total_count = max(total_count, len(nodes))
    incomplete = total_count > len(nodes) or more
    if incomplete:
        logger.warning(
            "PR #{}: read {} of {} review threads (page cap {} x {}); the listing is "
            "incomplete, so threads past it are neither swept nor resolved",
            pull_number,
            len(nodes),
            total_count,
            THREADS_MAX_PAGES,
            THREADS_PAGE_SIZE,
        )

    threads: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("isResolved") and not include_resolved:
            continue
        thread_id = str(node.get("id") or "")
        comment_nodes, _comment_total, comments_truncated = await _read_all_comments(
            scm, thread_id, node.get("comments") or {}
        )
        incomplete = incomplete or comments_truncated
        comments = [
            {
                "id": c.get("databaseId"),
                "body": c.get("body"),
                "author": (c.get("author") or {}).get("login"),
                "path": c.get("path"),
                "line": c.get("line") or c.get("originalLine"),
                "url": c.get("url"),
                "createdAt": c.get("createdAt"),
            }
            for c in comment_nodes
        ]
        threads.append(
            {
                "threadId": node.get("id"),
                "isResolved": node.get("isResolved"),
                "isOutdated": node.get("isOutdated"),
                "comments": comments,
                "commentsTruncated": comments_truncated,
            }
        )
    return ReviewThreadPage(threads=threads, total_count=total_count, incomplete=incomplete)


__all__ = [
    "COMMENTS_MAX_PAGES",
    "COMMENTS_PAGE_SIZE",
    "THREADS_MAX_PAGES",
    "THREADS_PAGE_SIZE",
    "THREADS_QUERY",
    "THREAD_COMMENTS_QUERY",
    "ReviewThreadPage",
    "fetch_review_threads",
]
