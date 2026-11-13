"""Test helpers for building and binding :class:`~mergecraft.mcp.context.ToolContext`.

Trust is never implicit here. :func:`make_tool_context` requires ``trust_tier``
as a keyword with no default, so every test that goes through it says which
tier it runs under. ``ToolContext``'s own default is the restrictive
``"untrusted"`` (unknown trust fails closed); a test that needs the permissive
tier has to ask for it by name.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Literal
from unittest.mock import patch

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.scm.github import GitHubScmAdapter, github_client_from_scm
from mergecraft.utils.github import GitHubClient
from tests.support.github_fakes import StrictGitHubClient

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.mcp.tool_state import ToolState
    from mergecraft.scm.protocol import ScmProvider

TrustTier = Literal["trusted", "untrusted"]


def make_tool_context(
    tmp_path: Path,
    *,
    trust_tier: TrustTier,
    github: GitHubClient | None = None,
    scm: ScmProvider | None = None,
    event: PayloadEvent | None = None,
    tool_state: ToolState | None = None,
    **overrides: Any,
) -> ToolContext:
    """Build a local ``acme/demo`` context with an explicit trust tier.

    ``trust_tier`` is required: the test states which tier it runs under
    instead of inheriting whatever ``ToolContext`` defaults to. ``overrides``
    are passed straight to the constructor (``pr_approve_enabled=True``,
    ``authority_trust="untrusted"``, …).
    """
    state = tool_state or init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    kwargs: dict[str, Any] = {
        "agent_id": "claude",
        "repo": RepoIdentity(owner="acme", name="demo"),
        "payload": ResolvedPayload(
            event=event or PayloadEvent(trigger="pull_request", issue_number=7, is_pr=True),
            shell="restricted",
        ),
        "github_installation_token": "",
        "git_token": "",
        "api_token": "",
        "modes": compute_modes("claude"),
        "tool_state": state,
        "mcp_server_url": "",
        "tmpdir": str(tmp_path),
        "trust_tier": trust_tier,
    }
    if scm is not None:
        kwargs["scm"] = scm
    else:
        kwargs["github"] = github or StrictGitHubClient(token="")
    kwargs.update(overrides)
    return ToolContext(**kwargs)


def bind_github_client(ctx: ToolContext, client: GitHubClient) -> None:
    """Replace ``ctx.scm`` with a GitHub adapter wrapping ``client``."""
    object.__setattr__(ctx, "scm", GitHubScmAdapter(client))


@contextmanager
def inner_mutation_guard_probe() -> Iterator[None]:
    """Exercise inner security guards while explicitly bypassing the outer mode gate.

    Production rejects every repository mutation. Tests separately assert that
    default-deny, then use this narrow seam to keep credential stripping, shell
    sandboxing and path confinement exercised rather than masked by that gate.
    """
    with patch("mergecraft.mcp.shared.guard_mutating_tool"):
        yield


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


def give_review_scope(ctx: ToolContext) -> ToolContext:
    """Record a materialized (hunk-free) diff as the run's review scope.

    A terminal verdict needs review scope even when no mode was selected, so a
    fixture that submits one without a checkout records the diff path here.
    """
    from pathlib import Path

    from mergecraft.mcp.tool_state import primary_repo_state

    primary = primary_repo_state(ctx.tool_state)
    if not primary.diff_path:
        diff_path = Path(ctx.tmpdir) / "scope.diff"
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_text("diff --git a/x b/x\n", encoding="utf-8")
        primary.diff_path = str(diff_path)
    return ctx
