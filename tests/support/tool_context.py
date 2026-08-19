"""Test helpers for binding GitHub clients on :class:`~mergecraft.mcp.context.ToolContext`."""

from __future__ import annotations

from mergecraft.mcp.context import ToolContext
from mergecraft.scm.github import GitHubScmAdapter, github_client_from_scm
from mergecraft.utils.github import GitHubClient


def bind_github_client(ctx: ToolContext, client: GitHubClient) -> None:
    """Replace ``ctx.scm`` with a GitHub adapter wrapping ``client``."""
    object.__setattr__(ctx, "scm", GitHubScmAdapter(client))


def github_client_from_ctx(ctx: ToolContext) -> GitHubClient:
    """Return the GitHub client bound on ``ctx.scm``."""
    client = github_client_from_scm(ctx.scm)
    if client is None:
        msg = "ToolContext.scm is not a GitHub adapter"
        raise RuntimeError(msg)
    return client
