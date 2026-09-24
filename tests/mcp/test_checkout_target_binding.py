"""S4 / TB-D4 — ``checkout_pr`` refuses an unbound or re-classified PR (TB1).

Wave plan: ``.ignorelocal/waves/40-trust-boundaries-wave-plan.md`` (TB1).

The classification S4 fixed happens in ``_resolve_credentials``; this suite
pins the checkout-side rebinding the plan adds in **TB-D4**:

* ``pull_number`` ≠ the run's bound ``ctx.payload.event.issue_number`` (when
  bound) → refuse;
* the fetched PR is a fork while ``ctx.trust_tier`` or ``ctx.authority_trust``
  is ``trusted`` → refuse (downgrading mid-run cannot un-run setup or un-mint
  credentials).

The positive cases (bound number on an untrusted run, no bound number) are
guards that pass today and must keep passing.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any, Literal

import pytest

from mergecraft.mcp.checkout import checkout_pr_tool
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _pr_repo(tmp_path: Path, *, pull_number: int = 1) -> Path:
    """Build an origin serving ``refs/pull/<pull_number>/head`` and return the clone."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "README.md").write_text("base\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", "base")
    _git(work, "branch", "-M", "base")
    _git(work, "checkout", "-b", "feature")
    (work / "feature.py").write_text("changed = 1\n", encoding="utf-8")
    _git(work, "add", "feature.py")
    _git(work, "commit", "-m", "feature")
    _git(work, "clone", "--bare", str(work), str(origin))
    _git(work, "push", str(origin), f"feature:refs/pull/{pull_number}/head")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(origin), str(clone))
    return clone


class _StubGitHub(GitHubClient):
    """Serves one PR whose fork-ness the test chooses."""

    def __init__(self, *, fork: bool) -> None:
        super().__init__(token="test-token")
        self._fork = fork

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        base_repo = {"full_name": f"{owner}/{repo}", "fork": False}
        head_repo = (
            {"full_name": "contributor/demo", "fork": True}
            if self._fork
            else {"full_name": f"{owner}/{repo}", "fork": False}
        )
        return {
            "number": pull_number,
            "head": {"ref": "feature", "sha": "a" * 40, "repo": head_repo},
            "base": {"ref": "base", "sha": "b" * 40, "repo": base_repo},
            "title": "A pull request",
            "html_url": f"https://example.test/pull/{pull_number}",
        }

    async def list_reviews(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        return []


def _ctx_for(
    repo: Path,
    github: GitHubClient,
    tmp_path: Path,
    *,
    bound_pr: int | None,
    trust_tier: Literal["trusted", "untrusted"] = "trusted",
    authority_trust: Literal["trusted", "untrusted"] | None = None,
    payload_event: PayloadEvent | None = None,
    gh_event: dict[str, Any] | None = None,
) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(repo))
    state.selected_mode = "Review"
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    event = (
        payload_event
        if payload_event is not None
        else PayloadEvent(trigger="issue_comment_created", issue_number=bound_pr, is_pr=True)
    )
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=event),
        github=github,
        tool_state=state,
        trust_tier=trust_tier,
        authority_trust=authority_trust,
        modes=compute_modes("claude"),
        tmpdir=str(tmp_path / "artifacts"),
        gh_event=gh_event,
    )


async def _call(ctx: ToolContext, pull_number: int) -> tuple[bool, str]:
    result = await checkout_pr_tool(ctx).execute({"pull_number": pull_number})
    return result.is_error, str(result.content[0]["text"])


@pytest.mark.asyncio
async def test_checkout_refuses_a_pull_number_the_run_was_not_bound_to(tmp_path: Path) -> None:
    """TB-D4 — the agent cannot redirect the run to a different PR."""
    repo = _pr_repo(tmp_path)
    ctx = _ctx_for(repo, _StubGitHub(fork=False), tmp_path, bound_pr=1)

    is_error, text = await _call(ctx, 2)

    assert is_error is True, text
    assert "bound" in text.lower() or "not the reviewed" in text.lower(), text


@pytest.mark.asyncio
async def test_checkout_refuses_a_fork_pr_on_a_trusted_run(tmp_path: Path) -> None:
    """TB-D4 — a trusted run may not check out a fork head."""
    repo = _pr_repo(tmp_path)
    ctx = _ctx_for(repo, _StubGitHub(fork=True), tmp_path, bound_pr=1, trust_tier="trusted")

    is_error, text = await _call(ctx, 1)

    assert is_error is True, text
    assert "fork" in text.lower(), text


@pytest.mark.asyncio
async def test_checkout_refuses_a_fork_pr_when_authority_trust_is_trusted(tmp_path: Path) -> None:
    """TB-D4 — either trust axis being ``trusted`` refuses the fork."""
    repo = _pr_repo(tmp_path)
    ctx = _ctx_for(
        repo,
        _StubGitHub(fork=True),
        tmp_path,
        bound_pr=1,
        trust_tier="untrusted",
        authority_trust="trusted",
    )

    is_error, text = await _call(ctx, 1)

    assert is_error is True, text
    assert "fork" in text.lower(), text


@pytest.mark.asyncio
async def test_checkout_allows_the_bound_same_repo_pull_number(tmp_path: Path) -> None:
    """Guard — the bound, same-repo PR checks out as before."""
    repo = _pr_repo(tmp_path)
    ctx = _ctx_for(repo, _StubGitHub(fork=False), tmp_path, bound_pr=1)

    is_error, text = await _call(ctx, 1)

    assert is_error is False, text


@pytest.mark.asyncio
async def test_checkout_allows_a_fork_pr_on_an_untrusted_run(tmp_path: Path) -> None:
    """Guard — an untrusted run already handles a fork head."""
    repo = _pr_repo(tmp_path)
    ctx = _ctx_for(repo, _StubGitHub(fork=True), tmp_path, bound_pr=1, trust_tier="untrusted")

    is_error, text = await _call(ctx, 1)

    assert is_error is False, text


@pytest.mark.asyncio
async def test_checkout_without_a_bound_pr_does_not_refuse_on_number(tmp_path: Path) -> None:
    """Guard — an unbound run (no PR number on the payload) is unchanged."""
    repo = _pr_repo(tmp_path)
    ctx = _ctx_for(repo, _StubGitHub(fork=False), tmp_path, bound_pr=None)

    is_error, text = await _call(ctx, 1)

    assert is_error is False, text


# ── TB6 — the bound number is read from ``ctx.gh_event``, not only the payload ─
#
# A ``workflow_dispatch`` (and a comment-on-PR) resolves no ``issue_number`` on
# the payload, so the pre-TB6 guard — which read ``ctx.payload.event.issue_number``
# alone — was inert on those runs. ``_resolve_credentials`` binds the fetched PR
# onto ``ctx.gh_event``; the guard now prefers that bound ``pull_request.number``
# and only falls back to the payload when the bound event has none.

_DISPATCH_EVENT = PayloadEvent(trigger="workflow_dispatch")


@pytest.mark.asyncio
async def test_checkout_refuses_a_dispatch_pull_number_the_run_was_not_bound_to(
    tmp_path: Path,
) -> None:
    """TB-D4 — on a dispatch run the bound number still governs the checkout.

    The payload carries no ``issue_number``; only ``ctx.gh_event`` knows the run
    is bound to PR #42. Checking out #43 must be refused.
    """
    repo = _pr_repo(tmp_path, pull_number=42)
    ctx = _ctx_for(
        repo,
        _StubGitHub(fork=False),
        tmp_path,
        bound_pr=None,
        payload_event=_DISPATCH_EVENT,
        gh_event={"pull_request": {"number": 42}},
    )

    is_error, text = await _call(ctx, 43)

    assert is_error is True, text
    assert "bound" in text.lower() or "not the reviewed" in text.lower(), text


@pytest.mark.asyncio
async def test_checkout_allows_the_dispatch_bound_pull_number(tmp_path: Path) -> None:
    """TB-D4 — the dispatch run's own bound PR #42 still checks out."""
    repo = _pr_repo(tmp_path, pull_number=42)
    ctx = _ctx_for(
        repo,
        _StubGitHub(fork=False),
        tmp_path,
        bound_pr=None,
        payload_event=_DISPATCH_EVENT,
        gh_event={"pull_request": {"number": 42}},
    )

    is_error, text = await _call(ctx, 42)

    assert is_error is False, text


@pytest.mark.asyncio
async def test_checkout_falls_back_to_the_payload_number_without_a_bound_pull_request(
    tmp_path: Path,
) -> None:
    """TB-D4 — ``gh_event`` present but with no ``pull_request`` still binds from the payload."""
    repo = _pr_repo(tmp_path)
    ctx = _ctx_for(
        repo,
        _StubGitHub(fork=False),
        tmp_path,
        bound_pr=1,
        gh_event={"action": "created"},
    )

    is_error, text = await _call(ctx, 2)

    assert is_error is True, text
    assert "bound" in text.lower() or "not the reviewed" in text.lower(), text


@pytest.mark.asyncio
async def test_checkout_ignores_a_non_integer_bound_number(tmp_path: Path) -> None:
    """TB-D4 — a non-integer ``number`` on the bound event is not a bound number.

    A naive ``bound_pr.get("number") is not None`` guard would compare ``1`` (a
    real PR number) against the string ``"42"`` and refuse the PR the run was
    actually bound to. A non-integer value does not bind.
    """
    repo = _pr_repo(tmp_path)
    ctx = _ctx_for(
        repo,
        _StubGitHub(fork=False),
        tmp_path,
        bound_pr=None,
        payload_event=_DISPATCH_EVENT,
        gh_event={"pull_request": {"number": "42"}},
    )

    is_error, text = await _call(ctx, 1)

    assert is_error is False, text


@pytest.mark.asyncio
async def test_checkout_without_a_bound_number_on_a_dispatch_is_permissive(
    tmp_path: Path,
) -> None:
    """Guard — a dispatch with no bound number anywhere keeps today's behaviour."""
    repo = _pr_repo(tmp_path)
    ctx = _ctx_for(
        repo,
        _StubGitHub(fork=False),
        tmp_path,
        bound_pr=None,
        payload_event=_DISPATCH_EVENT,
        gh_event={"action": "created"},
    )

    is_error, text = await _call(ctx, 1)

    assert is_error is False, text
