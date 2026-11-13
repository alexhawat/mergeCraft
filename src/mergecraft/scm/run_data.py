"""Optional run snapshots for SCM consumers, owned by their GitHub client.

Exports:
    read_run_data: Share a snapshot when the provider has a run-owned memo.
    run_memo: Resolve the memo without requiring it from other SCM implementations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from mergecraft.utils.run_memo import RunMemo

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Hashable

    from mergecraft.scm.protocol import ScmProvider

_T = TypeVar("_T")


def run_memo(scm: ScmProvider) -> RunMemo | None:
    """Return this provider's run memo, or keep unsupported providers uncached."""
    from mergecraft.scm.github import github_client_from_scm

    client = github_client_from_scm(scm)
    memo = getattr(client, "run_memo", None)
    return memo if isinstance(memo, RunMemo) else None


async def read_run_data(
    scm: ScmProvider, key: tuple[Hashable, ...], fetch: Callable[[], Awaitable[_T]]
) -> _T:
    """Read a snapshot once for the owning client, returning independent copies.

    Args:
        scm: Provider whose client owns the run and credential scope.
        key: Repository and immutable identity of the requested snapshot.
        fetch: Read and validate the requested data without mutating caller state.

    Returns:
        The snapshot, or an uncached read for providers without this capability.
    """
    memo = run_memo(scm)
    return await memo.read(key, fetch) if memo is not None else await fetch()
