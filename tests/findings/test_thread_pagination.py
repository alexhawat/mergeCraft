"""Review-thread retrieval pages through GitHub's connections and says when it stopped early.

``fetch_review_threads`` used to read one page of ``reviewThreads(first: 100)`` and one
page of ``comments(first: 100)`` per thread and returned whatever that was. On a pull
request with more, the rest were never seen. These tests pin the cursor loop, the page
cap, and the explicit ``incomplete`` marker the callers read — and that the fail-safe
(a thread that was not fully read is never auto-resolved) holds.

The GraphQL client is a fake that serves cursor pages; nothing touches the network.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.findings.threads import fetch_review_threads
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

_PAGE = 100


def _comment(index: int, *, body: str = "a comment") -> dict[str, Any]:
    return {
        "databaseId": index,
        "body": body,
        "author": {"login": "someone"},
        "path": "src/app.py",
        "line": 3,
        "originalLine": 3,
        "url": f"https://github.com/o/r/pull/7#discussion_r{index}",
        "createdAt": "2026-01-01T00:00:00Z",
    }


def _thread(thread_id: str, *, comments: int = 1, resolved: bool = False) -> dict[str, Any]:
    return {
        "id": thread_id,
        "isResolved": resolved,
        "isOutdated": False,
        "_all_comments": [_comment(n) for n in range(1, comments + 1)],
    }


class PagingGitHub(GitHubClient):
    """GraphQL fake that serves ``reviewThreads`` and per-thread ``comments`` by cursor."""

    def __init__(self, threads: list[dict[str, Any]], *, endless: bool = False) -> None:
        super().__init__(token="test-token")
        self._threads = threads
        self._endless = endless
        self.thread_calls: list[dict[str, Any]] = []
        self.comment_calls: list[dict[str, Any]] = []

    @staticmethod
    def _slice(rows: list[Any], cursor: str | None) -> tuple[list[Any], bool, str]:
        start = int(cursor.removeprefix("c")) if cursor else 0
        end = start + _PAGE
        return rows[start:end], end < len(rows), f"c{end}"

    def _comments_connection(self, thread: dict[str, Any], cursor: str | None) -> dict[str, Any]:
        rows = thread["_all_comments"]
        page, has_next, end_cursor = self._slice(rows, cursor)
        return {
            "totalCount": len(rows),
            "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
            "nodes": page,
        }

    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        variables = dict(variables or {})
        if "threadId" in variables:
            self.comment_calls.append(variables)
            thread = next(t for t in self._threads if t["id"] == variables["threadId"])
            return {
                "node": {"comments": self._comments_connection(thread, variables.get("cursor"))}
            }
        self.thread_calls.append(variables)
        cursor = variables.get("cursor")
        page, has_next, end_cursor = self._slice(self._threads, cursor)
        total = len(self._threads)
        if self._endless:
            # A pull request that never runs out: every page is full and says "more".
            number = len(self.thread_calls) - 1
            page = [_thread(f"E{number}-{n}") for n in range(_PAGE)]
            has_next, end_cursor, total = True, f"c{(number + 1) * _PAGE}", 10_000
        nodes = []
        for thread in page:
            node = {k: v for k, v in thread.items() if k != "_all_comments"}
            node["comments"] = self._comments_connection(thread, None)
            nodes.append(node)
        return {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "totalCount": total,
                        "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
                        "nodes": nodes,
                    }
                }
            }
        }


def _capture_warnings() -> tuple[list[str], int]:
    captured: list[str] = []
    sink_id = logger.add(lambda message: captured.append(str(message)), level="WARNING")
    return captured, sink_id


async def test_more_than_one_page_of_threads_are_all_returned() -> None:
    github = PagingGitHub([_thread(f"T{n}") for n in range(150)])

    page = await fetch_review_threads(github, "o", "r", 7)  # type: ignore[arg-type]

    assert [t["threadId"] for t in page.threads] == [f"T{n}" for n in range(150)]
    assert page.total_count == 150
    assert page.incomplete is False
    assert len(github.thread_calls) == 2
    assert github.thread_calls[0].get("cursor") is None
    assert github.thread_calls[1]["cursor"] == "c100"


async def test_a_thread_with_more_than_one_page_of_comments_is_read_in_full() -> None:
    github = PagingGitHub([_thread("T1", comments=230)])

    page = await fetch_review_threads(github, "o", "r", 7)  # type: ignore[arg-type]

    thread = page.threads[0]
    assert [c["id"] for c in thread["comments"]] == list(range(1, 231))
    assert thread["commentsTruncated"] is False
    assert page.incomplete is False
    assert [call["cursor"] for call in github.comment_calls] == ["c100", "c200"]


async def test_hitting_the_thread_page_cap_reports_incomplete_and_warns() -> None:
    from mergecraft.findings.threads import THREADS_MAX_PAGES

    github = PagingGitHub([], endless=True)
    captured, sink_id = _capture_warnings()
    try:
        page = await fetch_review_threads(github, "o", "r", 7)  # type: ignore[arg-type]
    finally:
        logger.remove(sink_id)

    assert page.incomplete is True
    assert len(github.thread_calls) == THREADS_MAX_PAGES
    assert any("incomplete" in line.lower() or "page cap" in line.lower() for line in captured)


async def test_a_thread_whose_comments_hit_the_cap_is_marked_truncated_and_page_incomplete() -> (
    None
):
    from mergecraft.findings.threads import COMMENTS_MAX_PAGES

    over_the_cap = _PAGE * (COMMENTS_MAX_PAGES + 2)
    github = PagingGitHub([_thread("T1", comments=over_the_cap)])
    captured, sink_id = _capture_warnings()
    try:
        page = await fetch_review_threads(github, "o", "r", 7)  # type: ignore[arg-type]
    finally:
        logger.remove(sink_id)

    thread = page.threads[0]
    assert thread["commentsTruncated"] is True
    assert len(thread["comments"]) == _PAGE * COMMENTS_MAX_PAGES
    assert page.incomplete is True
    assert captured, "a truncated thread must be named in a warning"


async def test_resolved_threads_are_still_filtered_across_pages() -> None:
    threads = [_thread(f"T{n}", resolved=(n % 2 == 0)) for n in range(150)]
    github = PagingGitHub(threads)

    page = await fetch_review_threads(github, "o", "r", 7)  # type: ignore[arg-type]
    assert len(page.threads) == 75
    assert page.total_count == 150

    everything = await fetch_review_threads(github, "o", "r", 7, include_resolved=True)  # type: ignore[arg-type]
    assert len(everything.threads) == 150


async def test_the_old_truncated_name_still_reads_the_same_signal() -> None:
    from mergecraft.findings.threads import THREADS_MAX_PAGES

    complete = await fetch_review_threads(PagingGitHub([_thread("T1")]), "o", "r", 7)  # type: ignore[arg-type]
    capped = await fetch_review_threads(
        PagingGitHub([], endless=True),  # type: ignore[arg-type]
        "o",
        "r",
        7,
    )

    assert complete.truncated is complete.incomplete is False
    assert capped.truncated is capped.incomplete is True
    assert THREADS_MAX_PAGES == 10


async def test_get_review_comments_tool_reports_incomplete_only_when_the_cap_was_hit(
    tmp_path: Path,
) -> None:
    from mergecraft.mcp.review_comments import get_review_comments_tool
    from tests.support.tool_context import make_tool_context

    for endless, expect in ((False, False), (True, True)):
        github = PagingGitHub([] if endless else [_thread("T1")], endless=endless)
        ctx = make_tool_context(tmp_path, trust_tier="trusted", github=github)
        result = await get_review_comments_tool(ctx).execute({"pull_number": 7})
        assert result.is_error is False
        payload = json.loads(result.content[0]["text"])
        assert payload.get("incomplete", False) is expect
        assert payload["count"] == len(payload["threads"])


async def test_a_thread_whose_comments_were_not_all_read_is_never_resolved() -> None:
    """Fail-safe: a human reply past the cap could be hiding, so nothing closes the thread."""
    from mergecraft.review_resolution import resolvable_thread_ids

    marker = "<!-- mergecraft-finding:v1:abc123 -->"
    body = f"A finding.\n{marker}\n*via mergecraft*"
    thread = {
        "threadId": "T1",
        "isResolved": False,
        "isOutdated": True,
        "commentsTruncated": True,
        "comments": [{"id": 1, "body": body, "author": "app[bot]", "path": "a.py", "line": 3}],
    }

    assert (
        resolvable_thread_ids(
            [thread],
            current_fingerprints=frozenset(),
            changed_lines={},
            publishers=frozenset({"app[bot]"}),
        )
        == []
    )
    complete = {**thread, "commentsTruncated": False}
    assert resolvable_thread_ids(
        [complete],
        current_fingerprints=frozenset(),
        changed_lines={},
        publishers=frozenset({"app[bot]"}),
    ) == ["T1"]
