"""Test doubles for SCM protocol behaviour — not imported by production code."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mergecraft.mcp.checkout import changed_paths_in_diff
from mergecraft.scm.protocol import ScmCapability

if TYPE_CHECKING:
    from mergecraft.scm.protocol import ScmProvider


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


def checkout_pull_request(
    provider: ScmProvider,
    *,
    owner: str,
    repo: str,
    pull_number: int,
    cwd: str,
    temp_dir: str,
    last_reviewed_sha: str | None = None,
) -> dict[str, Any]:
    """Protocol-test seam for checkout + incremental diff semantics.

    Production checkouts run through ``mergecraft.mcp.checkout``; this helper
    writes diff artifacts from provider-held diff text for protocol tests only.
    """
    _ = (owner, repo, cwd)
    diff_text = str(getattr(provider, "diff_text", "") or "")
    incremental_text = getattr(provider, "incremental_diff_text", None)

    diff_path = str(Path(temp_dir) / f"pr-{pull_number}.diff")
    Path(temp_dir).mkdir(parents=True, exist_ok=True)
    Path(diff_path).write_text(diff_text, encoding="utf-8")

    result: dict[str, Any] = {
        "pullNumber": pull_number,
        "diffPath": diff_path,
    }

    if last_reviewed_sha:
        inc_body = str(incremental_text if incremental_text is not None else diff_text)
        incremental_path = str(Path(temp_dir) / f"pr-{pull_number}-incremental.diff")
        Path(temp_dir).mkdir(parents=True, exist_ok=True)
        Path(incremental_path).write_text(inc_body, encoding="utf-8")
        result["incrementalDiffPath"] = incremental_path
        result["lastReviewedSha"] = last_reviewed_sha
        result["incrementalChangedPaths"] = changed_paths_in_diff(inc_body)

    return result
