"""Review-thread retrieval, shared by the MCP tool and the findings sweep.

The GraphQL document and its normalization live here so that
``get_review_comments`` — the tool the reviewing agent calls mid-run — and
``mergecraft findings`` — the post-merge sweep — read a pull request's threads
through exactly one shape. A second copy of this query would drift, and the two
callers disagreeing about what a thread looks like is precisely the failure the
carryover feature exists to prevent.

The query is single-page by design (GitHub's connection maxima), so the page
reports whether it saw everything. Callers that must not silently drop findings
check :attr:`ReviewThreadPage.truncated`.

Exports:
    ReviewThreadPage: Normalized threads plus the truncation signal.
    THREADS_QUERY: The GraphQL document this module issues.
    fetch_review_threads: Read one pull request's review threads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from mergecraft.scm.protocol import ScmProvider

# GitHub caps both connections at 100. Comments are read to that cap and their
# totalCount is kept: a human reply hiding past the cap would otherwise make an
# answered conversation look unanswered, which is how a sweep files an issue
# over somebody's explicit "not an issue".
THREADS_QUERY: Final[str] = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        totalCount
        nodes {
          id
          isResolved
          isOutdated
          comments(first: 100) {
            totalCount
            nodes {
              databaseId
              body
              author { login }
              path
              line
              originalLine
              url
              createdAt
            }
          }
        }
      }
    }
  }
}
"""


@dataclass(slots=True)
class ReviewThreadPage:
    """One page of review threads, in the shape ``get_review_comments`` returns.

    Attributes:
        threads: Normalized threads, already filtered by ``include_resolved``.
        total_count: How many threads the pull request has in total.
        truncated: Whether the pull request has more threads than one page holds.
    """

    threads: list[dict[str, Any]] = field(default_factory=list)
    total_count: int = 0
    truncated: bool = False


async def fetch_review_threads(
    scm: ScmProvider,
    owner: str,
    repo: str,
    pull_number: int,
    *,
    include_resolved: bool = False,
) -> ReviewThreadPage:
    """Return a pull request's review threads, normalized for every caller.

    Args:
        scm: SCM provider used for the GraphQL call.
        owner: Repository owner.
        repo: Repository name.
        pull_number: Pull request number.
        include_resolved: Keep threads GitHub reports as resolved.

    Returns:
        A :class:`ReviewThreadPage`. ``threads`` is empty when the pull request
        has none, or when every thread was filtered out as resolved.
    """
    data = await scm.graphql(
        THREADS_QUERY,
        {"owner": owner, "repo": repo, "number": pull_number},
    )
    connection = (((data or {}).get("repository") or {}).get("pullRequest") or {}).get(
        "reviewThreads"
    ) or {}
    nodes = connection.get("nodes") or []
    total_count = int(connection.get("totalCount") or len(nodes))

    threads: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("isResolved") and not include_resolved:
            continue
        comment_connection = node.get("comments") or {}
        comment_nodes = comment_connection.get("nodes") or []
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
        comment_total = int(comment_connection.get("totalCount") or len(comment_nodes))
        threads.append(
            {
                "threadId": node.get("id"),
                "isResolved": node.get("isResolved"),
                "isOutdated": node.get("isOutdated"),
                "comments": comments,
                "commentsTruncated": comment_total > len(comment_nodes),
            }
        )
    return ReviewThreadPage(
        threads=threads,
        total_count=total_count,
        truncated=total_count > len(nodes),
    )


__all__ = ["THREADS_QUERY", "ReviewThreadPage", "fetch_review_threads"]
