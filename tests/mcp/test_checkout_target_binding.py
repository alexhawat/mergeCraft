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

_TB2 = "green after TB2: checkout refuses an unbound or re-classified PR"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _pr_repo(tmp_path: Path) -> Path:
    """Build an origin serving ``refs/pull/1/head`` and return the clone."""
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
    _git(work, "push", str(origin), "feature:refs/pull/1/head")
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
) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(repo))
    state.selected_mode = "Review"
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="issue_comment_created", issue_number=bound_pr, is_pr=True)
        ),
        github=github,
        tool_state=state,
        trust_tier=trust_tier,
        authority_trust=authority_trust,
        modes=compute_modes("claude"),
        tmpdir=str(tmp_path / "artifacts"),
    )


async def _call(ctx: ToolContext, pull_number: int) -> tuple[bool, str]:
    result = await checkout_pr_tool(ctx).execute({"pull_number": pull_number})
    return result.is_error, str(result.content[0]["text"])


@pytest.mark.xfail(reason=_TB2, strict=False)
@pytest.mark.asyncio
async def test_checkout_refuses_a_pull_number_the_run_was_not_bound_to(tmp_path: Path) -> None:
    """TB-D4 — the agent cannot redirect the run to a different PR."""
    repo = _pr_repo(tmp_path)
    ctx = _ctx_for(repo, _StubGitHub(fork=False), tmp_path, bound_pr=1)

    is_error, text = await _call(ctx, 2)

    assert is_error is True, text
    assert "bound" in text.lower() or "not the reviewed" in text.lower(), text


@pytest.mark.xfail(reason=_TB2, strict=False)
@pytest.mark.asyncio
async def test_checkout_refuses_a_fork_pr_on_a_trusted_run(tmp_path: Path) -> None:
    """TB-D4 — a trusted run may not check out a fork head."""
    repo = _pr_repo(tmp_path)
    ctx = _ctx_for(repo, _StubGitHub(fork=True), tmp_path, bound_pr=1, trust_tier="trusted")

    is_error, text = await _call(ctx, 1)

    assert is_error is True, text
    assert "fork" in text.lower(), text


@pytest.mark.xfail(reason=_TB2, strict=False)
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
