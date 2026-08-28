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


def bind_review_publication_scope(
    ctx: ToolContext,
    *,
    pr_number: int = 7,
    checkout_sha: str = "deadbeef",
) -> None:
    """Bind immutable run identity required by AG2 publication gates."""
    from pathlib import Path

    from mergecraft.mcp.tool_state import primary_repo_state

    ctx.tool_state.pr_number = pr_number
    if ctx.tool_state.selected_mode is None:
        ctx.tool_state.selected_mode = "Review"
    primary = primary_repo_state(ctx.tool_state)
    primary.issue_number = pr_number
    primary.checkout_sha = checkout_sha
    diff_path = Path(ctx.tmpdir) / "diff.patch"
    diff_path.write_text("diff --git a/x b/x\n", encoding="utf-8")
    primary.diff_path = str(diff_path)
