"""An SCM stand-in that serves issue comments and PR reviews page by page.

GitHub's list endpoints return a bare JSON array per page and signal the end
with a short page. ``PagedListScm`` reproduces that: ``page``/``per_page`` come
from the request's ``params`` (``page`` defaults to 1, ``per_page`` to GitHub's
30), items are numbered oldest first from 1, and ``endless=True`` makes every
page full so a caller's page cap is the only way out.
"""

from __future__ import annotations

from typing import Any


class PagedListScm:
    """Records every list request and answers from a numbered, oldest-first list."""

    def __init__(self, *, total: int = 0, endless: bool = False) -> None:
        self.total = total
        self.endless = endless
        self.requests: list[dict[str, Any]] = []

    def _page(self, kind: str, params: dict[str, Any] | None) -> list[dict[str, Any]]:
        query = dict(params or {})
        page = int(query.get("page", 1))
        per_page = int(query.get("per_page", 30))
        self.requests.append({"kind": kind, "page": page, "per_page": per_page})
        start = (page - 1) * per_page + 1
        stop = start + per_page if self.endless else min(start + per_page, self.total + 1)
        return [self._item(kind, number) for number in range(start, stop)]

    @staticmethod
    def _item(kind: str, number: int) -> dict[str, Any]:
        if kind == "reviews":
            return {
                "id": number,
                "state": "COMMENTED",
                "body": f"review {number}",
                "user": {"login": "reviewer"},
                "submitted_at": f"2026-01-01T00:{number // 60 % 60:02d}:{number % 60:02d}Z",
                "commit_id": f"{number:040d}",
            }
        return {"id": number, "body": f"comment {number}", "user": {"login": "dev"}}

    async def list_issue_comments(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        *,
        params: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> list[dict[str, Any]]:
        del owner, repo, issue_number
        return self._page("comments", params)

    async def list_reviews(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        *,
        params: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> list[dict[str, Any]]:
        del owner, repo, pull_number
        return self._page("reviews", params)

    def pages(self, kind: str) -> list[int]:
        return [request["page"] for request in self.requests if request["kind"] == kind]


__all__ = ["PagedListScm"]
