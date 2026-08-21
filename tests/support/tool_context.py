"""Test helpers for binding GitHub clients on :class:`~mergecraft.mcp.context.ToolContext`."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from mergecraft.mcp.context import ToolContext
from mergecraft.mcp.shared import bind_selected_mode, reset_selected_mode
from mergecraft.scm.github import GitHubScmAdapter, github_client_from_scm
from mergecraft.utils.github import GitHubClient


def bind_github_client(ctx: ToolContext, client: GitHubClient) -> None:
    """Replace ``ctx.scm`` with a GitHub adapter wrapping ``client``."""
    object.__setattr__(ctx, "scm", GitHubScmAdapter(client))


@contextmanager
def write_capable_mcp_mode(name: str = "Fix") -> Iterator[None]:
    """Bind a write-capable mode so mutating MCP tools can run their inner guards.

    Production has no write-capable modes; tests use this only to reach
    git/shell/env stripping after the review-only default-deny.
    """
    token = bind_selected_mode(name)
    try:
        yield
    finally:
        reset_selected_mode(token)


def github_client_from_ctx(ctx: ToolContext) -> GitHubClient:
    """Return the GitHub client bound on ``ctx.scm``."""
    client = github_client_from_scm(ctx.scm)
    if client is None:
        msg = "ToolContext.scm is not a GitHub adapter"
        raise RuntimeError(msg)
    return client
