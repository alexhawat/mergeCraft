"""One bounded files walk shared by review consumers at a verified PR identity.

Exports:
    list_pull_files: Read the complete bounded listing, retaining truncation information.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.scm.run_data import run_memo
from mergecraft.scm.types import ListedItems

if TYPE_CHECKING:
    from mergecraft.scm.protocol import ScmProvider


def _identity(pull: dict[str, Any]) -> tuple[str, str]:
    head, base = pull.get("head"), pull.get("base")
    head_sha = head.get("sha") if isinstance(head, dict) else None
    base_sha = base.get("sha") if isinstance(base, dict) else None
    if (
        not isinstance(head_sha, str)
        or not head_sha
        or not isinstance(base_sha, str)
        or not base_sha
    ):
        raise RuntimeError("cannot bind the files listing to the PR head and base")
    return head_sha.lower(), base_sha.lower()


async def list_pull_files(
    scm: ScmProvider,
    owner: str,
    repo: str,
    pull_number: int,
    *,
    head_sha: str | None = None,
    page_size: int = 100,
    max_pages: int = 30,
) -> ListedItems:
    """Share files only when their PR head and base identities still match.

    Args:
        scm: Provider whose run-owned memo may share the listing.
        owner: Repository owner.
        repo: Repository name.
        pull_number: Pull request number.
        head_sha: Required head when the caller is already bound to a revision.
        page_size: Number of entries requested per page.
        max_pages: Bounded number of pages; reaching the cap marks the result incomplete.

    Returns:
        File rows including rename/patch metadata, plus the completeness flag.

    Raises:
        RuntimeError: The listing is malformed or its PR identity changed during the walk.
    """

    async def fetch() -> ListedItems:
        items: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            payload = await scm.get(
                f"/repos/{owner}/{repo}/pulls/{pull_number}/files",
                params={"per_page": page_size, "page": page},
            )
            batch = list(payload or [])
            if any(not isinstance(row, dict) for row in batch):
                raise RuntimeError("the PR files listing contains an invalid entry")
            items.extend(batch)
            if len(batch) < page_size:
                return ListedItems(items=items, incomplete=False)
        return ListedItems(items=items, incomplete=True)

    memo = run_memo(scm)
    if memo is None:
        return await fetch()
    # get_pull intentionally stays live: cached metadata must never satisfy a guard.
    before = _identity(await scm.get_pull(owner, repo, pull_number))
    if head_sha and before[0] != head_sha.lower():
        raise RuntimeError("the PR head changed before reading its files")

    async def verified_fetch() -> ListedItems:
        result = await fetch()
        after = _identity(await scm.get_pull(owner, repo, pull_number))
        if after != before:
            raise RuntimeError("the PR head changed or its base changed while reading its files")
        return result

    return await memo.read(
        ("pull-files", owner, repo, pull_number, *before, page_size, max_pages), verified_fetch
    )
