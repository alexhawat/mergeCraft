"""Test doubles for SCM protocol behaviour — not imported by production code."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mergecraft.scm.protocol import ScmCapability


@dataclass
class RecordingScmProvider:
    """In-memory provider that records review publications."""

    publications: list[dict[str, Any]] = field(default_factory=list)
    _review_counter: int = 0

    @property
    def capabilities(self) -> frozenset[ScmCapability]:
        return frozenset(ScmCapability)

    async def aclose(self) -> None:
        return None

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **fields: Any
    ) -> dict[str, Any]:
        self._review_counter += 1
        self.publications.append(
            {
                "owner": owner,
                "repo": repo,
                "pull_number": pull_number,
                "fields": dict(fields),
            }
        )
        return {"id": self._review_counter, "state": fields.get("event", "COMMENT")}

    async def create_pull_request_review(
        self, owner: str, repo: str, pull_number: int, **fields: Any
    ) -> dict[str, Any]:
        return await self.create_review(owner, repo, pull_number, **fields)


@dataclass
class InMemoryScmProvider:
    """Deterministic provider for checkout semantics tests."""

    reviews: list[dict[str, Any]]
    pull: dict[str, Any]
    diff_text: str
    incremental_diff_text: str | None = None

    @property
    def capabilities(self) -> frozenset[ScmCapability]:
        return frozenset({ScmCapability.CHECK_SUITES})

    def reviews_payload(self) -> list[dict[str, Any]]:
        return list(self.reviews)

    async def aclose(self) -> None:
        return None

    async def get_pull(self, _owner: str, _repo: str, _pull_number: int) -> dict[str, Any]:
        return dict(self.pull)

    async def list_reviews(
        self, _owner: str, _repo: str, _pull_number: int, **_kwargs: Any
    ) -> list[dict[str, Any]]:
        return self.reviews_payload()

    async def get(self, path: str, **_kwargs: Any) -> Any:
        if path.endswith("/files"):
            return []
        return []
