"""Tests for checkout_pr base-ref helpers and incremental-diff emission."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Literal

import pytest

from mergecraft.mcp.checkout import (
    changed_paths_in_diff,
    checkout_pr_tool,
    ensure_local_base_branch_alias,
    last_reviewed_sha,
    review_round_index,
)
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_origin_with_base(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "README.md").write_text("base\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", "base")
    _git(work, "branch", "-M", "pre-0.0.1")
    _git(work, "clone", "--bare", str(work), str(origin))
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(origin), str(clone))
    return clone


def test_ensure_local_base_branch_alias_creates_bare_base_name(tmp_path: Path) -> None:
    repo = _init_origin_with_base(tmp_path)
    _git(repo, "checkout", "-b", "pr-1")
    ensure_local_base_branch_alias(cwd=str(repo), base_ref="pre-0.0.1")
    shown = subprocess.check_output(
        ["git", "show", "pre-0.0.1:README.md"],
        cwd=repo,
        text=True,
    )
    assert shown == "base\n"


def test_ensure_local_base_branch_alias_noop_when_base_already_resolves(tmp_path: Path) -> None:
    repo = _init_origin_with_base(tmp_path)
    ensure_local_base_branch_alias(cwd=str(repo), base_ref="pre-0.0.1")
    shown = subprocess.check_output(
        ["git", "show", "pre-0.0.1:README.md"],
        cwd=repo,
        text=True,
    )
    assert shown == "base\n"


def test_ensure_local_base_branch_alias_noop_on_empty_ref(tmp_path: Path) -> None:
    repo = _init_origin_with_base(tmp_path)
    ensure_local_base_branch_alias(cwd=str(repo), base_ref="")


# ── incremental diff (C4) ─────────────────────────────────────────────────────

_MERGECRAFT_BODY = "### Review\n\n---\n*via mergecraft*"

# TB-D7 — the run's expected-publisher set. These fixtures model an App-published
# review (``<app-slug>[bot]``); the authorship filter is exercised directly in
# ``tests/review/test_authorship.py``.
_PUBLISHER_LOGIN = "mergecraft[bot]"
_BOT_USER: dict[str, str] = {"login": _PUBLISHER_LOGIN, "type": "Bot"}


def _pin_publishers(monkeypatch: pytest.MonkeyPatch, logins: frozenset[str]) -> None:
    """Pin the expected-publisher set for the checkpoint/round tests (TB-D7).

    Direct attribute access on both modules: a missing seam fails loudly here
    instead of silently leaving the test to exercise the real lookup.
    """
    import mergecraft.review.authorship as authorship
    from mergecraft.mcp import checkout as checkout_module

    monkeypatch.setattr(authorship, "expected_publisher_logins", lambda ctx: logins)
    monkeypatch.setattr(checkout_module, "expected_publisher_logins", lambda ctx: logins)


def test_last_reviewed_sha_picks_the_newest_mergecraft_review() -> None:
    reviews = [
        {"commit_id": "a" * 40, "body": _MERGECRAFT_BODY, "user": _BOT_USER},
        {"commit_id": "b" * 40, "body": "LGTM from a human"},
        {"commit_id": "c" * 40, "body": _MERGECRAFT_BODY, "user": _BOT_USER},
    ]
    assert last_reviewed_sha(reviews, head_sha="d" * 40) == "c" * 40


def test_last_reviewed_sha_ignores_other_authors_and_the_current_head() -> None:
    assert last_reviewed_sha([{"commit_id": "a" * 40, "body": "nice"}], head_sha="d" * 40) is None
    assert (
        last_reviewed_sha(
            [{"commit_id": "a" * 40, "body": _MERGECRAFT_BODY, "user": _BOT_USER}],
            head_sha="A" * 40,
        )
        is None
    )
    assert (
        last_reviewed_sha(
            [{"commit_id": None, "body": _MERGECRAFT_BODY, "user": _BOT_USER}], head_sha="d"
        )
        is None
    )
    assert last_reviewed_sha([], head_sha="d" * 40) is None


# ── TB-D7: the checkpoint trusts marker AND publisher ────────────────────────


def test_last_reviewed_sha_ignores_a_marker_from_an_unexpected_author() -> None:
    """A marker posted by anyone who can review must not move the checkpoint."""
    reviews = [
        {
            "commit_id": "a" * 40,
            "body": _MERGECRAFT_BODY,
            "user": {"login": "random-user", "type": "User"},
        }
    ]
    assert (
        last_reviewed_sha(reviews, head_sha="d" * 40, publishers=frozenset({_PUBLISHER_LOGIN}))
        is None
    )


def test_last_reviewed_sha_ignores_a_marker_from_another_app_bot() -> None:
    """Another App's bot is bot-shaped but is not this run's publisher."""
    reviews = [
        {
            "commit_id": "a" * 40,
            "body": _MERGECRAFT_BODY,
            "user": {"login": "other-app[bot]", "type": "Bot"},
        }
    ]
    assert (
        last_reviewed_sha(reviews, head_sha="d" * 40, publishers=frozenset({_PUBLISHER_LOGIN}))
        is None
    )


def test_last_reviewed_sha_counts_a_marker_from_the_publishing_login() -> None:
    """A PAT-published run's own login is an expected publisher."""
    reviews = [
        {
            "commit_id": "c" * 40,
            "body": _MERGECRAFT_BODY,
            "user": {"login": "mergecraft-ci", "type": "User"},
        }
    ]
    assert (
        last_reviewed_sha(reviews, head_sha="d" * 40, publishers=frozenset({"mergecraft-ci"}))
        == "c" * 40
    )


def test_review_round_index_ignores_unexpected_authors() -> None:
    """The round count uses the same authorship rule as the checkpoint."""
    reviews = [
        {"commit_id": "a" * 40, "body": _MERGECRAFT_BODY, "user": {"login": "random-user"}},
        {"commit_id": "b" * 40, "body": _MERGECRAFT_BODY, "user": _BOT_USER},
    ]
    assert review_round_index(reviews, publishers=frozenset({_PUBLISHER_LOGIN})) == 2


# ── TB6 pin: the shared Actions job bot never advances the checkpoint ────────
#
# These drive the *real* expected-publisher resolution (no monkeypatched
# ``publishers=``) so they pin the integration seam: a job-token run resolves to
# the empty set because ``github-actions[bot]`` is withheld, and therefore a
# marker review authored by it cannot move ``last_reviewed_sha`` or the round
# count. The App-publisher path still advances both — the over-correction guard.

_JOB_BOT_USER: dict[str, str] = {"login": "github-actions[bot]", "type": "Bot"}


class _AuthorshipScm:
    """Minimal SCM stub answering the authorship lookups (``/app``, ``/user``)."""

    def __init__(self, *, app_response: Any = None, user_response: Any = None) -> None:
        self._app_response = app_response
        self._user_response = user_response

    async def get(self, path: str, **kwargs: Any) -> Any:
        if path.rstrip("/").endswith("/app"):
            return self._app_response
        if path.rstrip("/").endswith("/user"):
            return self._user_response
        return None

    async def aclose(self) -> None:
        return None


def _real_publishers(
    monkeypatch: pytest.MonkeyPatch,
    dir_: str,
    *,
    token: str,
    app_response: Any = None,
    user_response: Any = None,
) -> frozenset[str]:
    """Resolve the run's expected-publisher set from production code."""
    for name in ("MERGECRAFT_REVIEWER_BOT_LOGIN", "GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY"):
        monkeypatch.delenv(name, raising=False)
    state = init_tool_state(owner="acme", name="demo", dir=dir_)
    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request_synchronize")),
        scm=_AuthorshipScm(app_response=app_response, user_response=user_response),  # type: ignore[arg-type]
        tool_state=state,
        github_installation_token=token,
        tmpdir=dir_,
    )
    from mergecraft.review.authorship import expected_publisher_logins

    return expected_publisher_logins(ctx)


def _job_token_run_publishers(monkeypatch: pytest.MonkeyPatch, dir_: str) -> frozenset[str]:
    monkeypatch.setenv("INPUT_TOKEN", "job-token")
    monkeypatch.setenv("GITHUB_TOKEN", "job-token")
    return _real_publishers(monkeypatch, dir_, token="job-token")


def test_last_reviewed_sha_does_not_adopt_a_github_actions_bot_review_on_a_job_token_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A forged checkpoint via the shared job bot must be refused (P-17)."""
    publishers = _job_token_run_publishers(monkeypatch, str(tmp_path))
    reviews = [{"commit_id": "a" * 40, "body": _MERGECRAFT_BODY, "user": _JOB_BOT_USER}]

    assert publishers == frozenset()
    assert last_reviewed_sha(reviews, head_sha="d" * 40, publishers=publishers) is None


def test_review_round_index_ignores_a_github_actions_bot_review_on_a_job_token_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The round count must not advance on a forged shared-bot review (P-17)."""
    publishers = _job_token_run_publishers(monkeypatch, str(tmp_path))
    reviews = [{"commit_id": "a" * 40, "body": _MERGECRAFT_BODY, "user": _JOB_BOT_USER}]

    assert publishers == frozenset()
    assert review_round_index(reviews, publishers=publishers) == 1


def test_app_publisher_still_advances_the_checkpoint_and_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard — the App-published path is never collateral damage."""
    publishers = _real_publishers(
        monkeypatch, str(tmp_path), token="", app_response={"slug": "mergecraft"}
    )
    reviews = [{"commit_id": "a" * 40, "body": _MERGECRAFT_BODY, "user": _BOT_USER}]

    assert "mergecraft[bot]" in publishers
    assert last_reviewed_sha(reviews, head_sha="d" * 40, publishers=publishers) == "a" * 40
    assert review_round_index(reviews, publishers=publishers) == 2


class _PagedReviewsGitHub(GitHubClient):
    """Serves review history page by page, recording the pages requested."""

    def __init__(self, *, pages: dict[int, list[dict[str, Any]]]) -> None:
        super().__init__(token="test-token")
        self._pages = pages
        self.page_requests: list[int] = []

    async def list_reviews(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        params = kwargs.get("params") or {}
        page = int(params.get("page", 1))
        self.page_requests.append(page)
        return list(self._pages.get(page, []))


def _reviews_ctx(github: GitHubClient, tmp_path: Path) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request_synchronize")),
        github=github,
        tool_state=state,
        tmpdir=str(tmp_path),
    )


@pytest.mark.asyncio
async def test_list_mergecraft_reviews_paginates_to_find_the_newest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TB-D7 — the newest mergeCraft review may live past the first page."""
    _pin_publishers(monkeypatch, frozenset({_PUBLISHER_LOGIN}))
    newest = {
        "commit_id": "c" * 40,
        "body": _MERGECRAFT_BODY,
        "user": _BOT_USER,
    }
    page_one = [
        {"commit_id": f"{i:040d}", "body": "human review", "user": {"login": "dev"}}
        for i in range(100)
    ]
    github = _PagedReviewsGitHub(pages={1: page_one, 2: [newest]})
    ctx = _reviews_ctx(github, tmp_path)

    from mergecraft.mcp.checkout import list_mergecraft_reviews

    reviews = await list_mergecraft_reviews(ctx, pull_number=1)

    assert newest in reviews
    assert github.page_requests == [1, 2]


@pytest.mark.asyncio
async def test_list_mergecraft_reviews_returns_oldest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TB-D7 — callers rely on GitHub's documented oldest-first order."""
    _pin_publishers(monkeypatch, frozenset({_PUBLISHER_LOGIN}))
    older = {"commit_id": "a" * 40, "body": _MERGECRAFT_BODY, "user": _BOT_USER}
    newer = {"commit_id": "b" * 40, "body": _MERGECRAFT_BODY, "user": _BOT_USER}
    github = _PagedReviewsGitHub(pages={1: [older, newer]})
    ctx = _reviews_ctx(github, tmp_path)

    from mergecraft.mcp.checkout import list_mergecraft_reviews

    reviews = await list_mergecraft_reviews(ctx, pull_number=1)

    assert reviews == [older, newer]


@pytest.mark.asyncio
async def test_list_mergecraft_reviews_drops_marker_reviews_from_other_authors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TB-D7 — history is filtered through the authorship rule."""
    _pin_publishers(monkeypatch, frozenset({_PUBLISHER_LOGIN}))
    foreign = {
        "commit_id": "a" * 40,
        "body": _MERGECRAFT_BODY,
        "user": {"login": "random-user", "type": "User"},
    }
    mine = {"commit_id": "b" * 40, "body": _MERGECRAFT_BODY, "user": _BOT_USER}
    github = _PagedReviewsGitHub(pages={1: [foreign, mine]})
    ctx = _reviews_ctx(github, tmp_path)

    from mergecraft.mcp.checkout import list_mergecraft_reviews

    reviews = await list_mergecraft_reviews(ctx, pull_number=1)

    assert reviews == [mine]


def test_changed_paths_in_diff_reads_post_image_paths() -> None:
    diff = (
        "diff --git a/src/a.py b/src/a.py\n@@ -1 +1 @@\n-x\n+y\n"
        "diff --git a/old.py b/new.py\nsimilarity index 100%\n"
    )
    assert changed_paths_in_diff(diff) == ["src/a.py", "new.py"]


class _StubGitHub(GitHubClient):
    """Serves one PR and its prior reviews without touching the network."""

    def __init__(self, *, head_sha: str, reviews: list[dict[str, Any]]) -> None:
        super().__init__(token="test-token")
        self._head_sha = head_sha
        self._reviews = reviews

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        repo_ref = {"full_name": f"{owner}/{repo}"}
        return {
            "head": {"ref": "feature", "sha": self._head_sha, "repo": repo_ref},
            "base": {"ref": "base", "repo": repo_ref},
            "title": "A pull request",
            "html_url": "https://x/1",
        }

    async def list_reviews(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        return list(self._reviews)


def _pr_repo_with_two_commits(tmp_path: Path) -> tuple[Path, str, str]:
    """Build an origin serving ``refs/pull/1/head`` and return (clone, first_sha, head_sha)."""
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
    (work / "reviewed.py").write_text("reviewed = 1\n", encoding="utf-8")
    _git(work, "add", "reviewed.py")
    _git(work, "commit", "-m", "already reviewed")
    first = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=work, text=True).strip()
    (work / "new.py").write_text("added_after_review = 1\n", encoding="utf-8")
    _git(work, "add", "new.py")
    _git(work, "commit", "-m", "pushed after the review")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=work, text=True).strip()
    _git(work, "clone", "--bare", str(work), str(origin))
    _git(work, "push", str(origin), "feature:refs/pull/1/head")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(origin), str(clone))
    return clone, first, head


def _pr_repo_with_impact_enabled(tmp_path: Path) -> tuple[Path, str]:
    """Build an origin whose PR branch enables ``analyzers.impact`` and adds a
    declaration, for exercising the ``impactPath`` wiring in ``checkout_pr``."""
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
    (work / ".mergecraft").mkdir()
    (work / ".mergecraft" / "config.yaml").write_text(
        "analyzers:\n  impact: true\n", encoding="utf-8"
    )
    (work / "src").mkdir()
    (work / "src" / "app.py").write_text("def changed():\n    return True\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "enable impact + add app.py")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=work, text=True).strip()
    _git(work, "clone", "--bare", str(work), str(origin))
    _git(work, "push", str(origin), "feature:refs/pull/1/head")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(origin), str(clone))
    return clone, head


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _exists(path: str) -> bool:
    return Path(path).is_file()


def _ctx_for(
    repo: Path,
    github: GitHubClient,
    tmp_path: Path,
    *,
    mode: str,
    trust_tier: Literal["trusted", "untrusted"] = "trusted",
    analyzers_mode: Literal["off", "auto", "full", "untrusted-only"] = "auto",
) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(repo))
    state.selected_mode = mode
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request_synchronize")),
        github=github,
        github_installation_token="",
        git_token="",
        api_token="",
        trust_tier=trust_tier,
        analyzers_mode=analyzers_mode,
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path / "artifacts"),
    )


async def _checkout(ctx: ToolContext) -> dict[str, Any]:
    result = await checkout_pr_tool(ctx).execute({"pull_number": 1})
    assert result.is_error is False, result.content[0]["text"]
    return json.loads(result.content[0]["text"])


@pytest.mark.asyncio
async def test_checkout_pr_succeeds_when_local_branch_already_checked_out(
    tmp_path: Path,
) -> None:
    """Regression: a second checkout_pr call in the same shared workspace
    (e.g. a Nous review, then a Codex fallback, both calling checkout_pr
    against the same /github/workspace within one job) must not fail with
    "refusing to fetch into branch ... checked out" just because the first
    call already left HEAD on the PR's local branch.
    """
    clone, _first, head = _pr_repo_with_two_commits(tmp_path)
    github = _StubGitHub(head_sha=head, reviews=[])
    ctx = _ctx_for(clone, github, tmp_path, mode="Review")

    first = await _checkout(ctx)
    second = await _checkout(ctx)

    assert first["pullNumber"] == 1
    assert second["pullNumber"] == 1
    assert second["localBranch"] == "pr-1"


@pytest.mark.asyncio
async def test_incremental_diff_covers_only_commits_since_the_last_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, reviewed_sha, head_sha = _pr_repo_with_two_commits(tmp_path)
    monkeypatch.delenv("MERGECRAFT_TEMP_DIR", raising=False)
    _pin_publishers(monkeypatch, frozenset({_PUBLISHER_LOGIN}))
    github = _StubGitHub(
        head_sha=head_sha,
        reviews=[{"commit_id": reviewed_sha, "body": _MERGECRAFT_BODY, "user": _BOT_USER}],
    )
    ctx = _ctx_for(repo, github, tmp_path, mode="IncrementalReview")

    payload = await _checkout(ctx)

    incremental = payload["incrementalDiffPath"]
    assert _exists(incremental)
    text = _read(incremental)
    assert "new.py" in text
    assert "reviewed.py" not in text
    assert payload["lastReviewedSha"] == reviewed_sha
    assert "reviewed.py" in _read(payload["diffPath"])
    primary = primary_repo_state(ctx.tool_state)
    assert primary.incremental_changed_paths == ["new.py"]


@pytest.mark.asyncio
async def test_incremental_key_is_omitted_without_a_prior_mergecraft_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, reviewed_sha, head_sha = _pr_repo_with_two_commits(tmp_path)
    monkeypatch.delenv("MERGECRAFT_TEMP_DIR", raising=False)
    github = _StubGitHub(
        head_sha=head_sha,
        reviews=[{"commit_id": reviewed_sha, "body": "looks fine to me"}],
    )
    ctx = _ctx_for(repo, github, tmp_path, mode="IncrementalReview")

    payload = await _checkout(ctx)

    assert "incrementalDiffPath" not in payload
    assert _exists(payload["diffPath"])


@pytest.mark.asyncio
async def test_incremental_key_is_omitted_outside_incremental_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, reviewed_sha, head_sha = _pr_repo_with_two_commits(tmp_path)
    monkeypatch.delenv("MERGECRAFT_TEMP_DIR", raising=False)
    _pin_publishers(monkeypatch, frozenset({_PUBLISHER_LOGIN}))
    github = _StubGitHub(
        head_sha=head_sha,
        reviews=[{"commit_id": reviewed_sha, "body": _MERGECRAFT_BODY, "user": _BOT_USER}],
    )
    ctx = _ctx_for(repo, github, tmp_path, mode="Review")

    payload = await _checkout(ctx)

    assert "incrementalDiffPath" not in payload


@pytest.mark.asyncio
async def test_incremental_key_is_omitted_when_the_prior_sha_is_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _reviewed_sha, head_sha = _pr_repo_with_two_commits(tmp_path)
    monkeypatch.delenv("MERGECRAFT_TEMP_DIR", raising=False)
    _pin_publishers(monkeypatch, frozenset({_PUBLISHER_LOGIN}))
    github = _StubGitHub(
        head_sha=head_sha,
        reviews=[{"commit_id": "0" * 40, "body": _MERGECRAFT_BODY, "user": _BOT_USER}],
    )
    ctx = _ctx_for(repo, github, tmp_path, mode="IncrementalReview")

    payload = await _checkout(ctx)

    assert "incrementalDiffPath" not in payload


@pytest.mark.asyncio
async def test_impact_path_present_when_enabled_and_binary_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.mcp import checkout as checkout_module

    repo, head_sha = _pr_repo_with_impact_enabled(tmp_path)
    monkeypatch.delenv("MERGECRAFT_TEMP_DIR", raising=False)
    monkeypatch.setattr(checkout_module, "resolve_ast_grep_binary", lambda: "ast-grep")
    github = _StubGitHub(head_sha=head_sha, reviews=[])
    ctx = _ctx_for(repo, github, tmp_path, mode="Review")

    payload = await _checkout(ctx)

    assert "impactPath" in payload
    assert _exists(payload["impactPath"])
    data = json.loads(_read(payload["impactPath"]))
    decl_names = {r["declaration"] for r in data["impactPath"]}
    assert "changed" in decl_names


@pytest.mark.asyncio
async def test_impact_path_omitted_when_ast_grep_binary_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.mcp import checkout as checkout_module

    repo, head_sha = _pr_repo_with_impact_enabled(tmp_path)
    monkeypatch.delenv("MERGECRAFT_TEMP_DIR", raising=False)
    monkeypatch.setattr(checkout_module, "resolve_ast_grep_binary", lambda: None)
    github = _StubGitHub(head_sha=head_sha, reviews=[])
    ctx = _ctx_for(repo, github, tmp_path, mode="Review")

    payload = await _checkout(ctx)

    assert "impactPath" not in payload


@pytest.mark.asyncio
async def test_impact_path_omitted_for_untrusted_checkout_without_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fork PR (untrusted trust tier) enabling analyzers.impact in its own
    checked-out config must not get ast-grep run unsandboxed against its own
    source — outside CI there is no sandbox isolation available, so the
    artifact is suppressed rather than executed without isolation (D7)."""
    from mergecraft.mcp import checkout as checkout_module

    repo, head_sha = _pr_repo_with_impact_enabled(tmp_path)
    monkeypatch.delenv("MERGECRAFT_TEMP_DIR", raising=False)
    monkeypatch.setattr(checkout_module, "resolve_ast_grep_binary", lambda: "ast-grep")
    github = _StubGitHub(head_sha=head_sha, reviews=[])
    ctx = _ctx_for(repo, github, tmp_path, mode="Review", trust_tier="untrusted")

    payload = await _checkout(ctx)

    assert "impactPath" not in payload


@pytest.mark.asyncio
async def test_impact_path_omitted_when_operator_disables_analyzers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The operator's effective analyzer policy (analyzers: off) must win over
    whatever a PR sets in its own analyzers.impact — a PR cannot self-enable
    ast-grep execution once the operator has switched analyzers off."""
    from mergecraft.mcp import checkout as checkout_module

    repo, head_sha = _pr_repo_with_impact_enabled(tmp_path)
    monkeypatch.delenv("MERGECRAFT_TEMP_DIR", raising=False)
    monkeypatch.setattr(checkout_module, "resolve_ast_grep_binary", lambda: "ast-grep")
    github = _StubGitHub(head_sha=head_sha, reviews=[])
    ctx = _ctx_for(repo, github, tmp_path, mode="Review", analyzers_mode="off")

    payload = await _checkout(ctx)

    assert "impactPath" not in payload
