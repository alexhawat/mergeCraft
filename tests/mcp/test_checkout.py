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


def test_last_reviewed_sha_picks_the_newest_mergecraft_review() -> None:
    reviews = [
        {"commit_id": "a" * 40, "body": _MERGECRAFT_BODY},
        {"commit_id": "b" * 40, "body": "LGTM from a human"},
        {"commit_id": "c" * 40, "body": _MERGECRAFT_BODY},
    ]
    assert last_reviewed_sha(reviews, head_sha="d" * 40) == "c" * 40


def test_last_reviewed_sha_ignores_other_authors_and_the_current_head() -> None:
    assert last_reviewed_sha([{"commit_id": "a" * 40, "body": "nice"}], head_sha="d" * 40) is None
    assert (
        last_reviewed_sha([{"commit_id": "a" * 40, "body": _MERGECRAFT_BODY}], head_sha="A" * 40)
        is None
    )
    assert last_reviewed_sha([{"commit_id": None, "body": _MERGECRAFT_BODY}], head_sha="d") is None
    assert last_reviewed_sha([], head_sha="d" * 40) is None


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
async def test_incremental_diff_covers_only_commits_since_the_last_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, reviewed_sha, head_sha = _pr_repo_with_two_commits(tmp_path)
    monkeypatch.delenv("MERGECRAFT_TEMP_DIR", raising=False)
    github = _StubGitHub(
        head_sha=head_sha,
        reviews=[{"commit_id": reviewed_sha, "body": _MERGECRAFT_BODY}],
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
    github = _StubGitHub(
        head_sha=head_sha,
        reviews=[{"commit_id": reviewed_sha, "body": _MERGECRAFT_BODY}],
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
    github = _StubGitHub(
        head_sha=head_sha,
        reviews=[{"commit_id": "0" * 40, "body": _MERGECRAFT_BODY}],
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
    monkeypatch.setattr(checkout_module, "resolve_ast_grep_binary", lambda repo_root: "ast-grep")
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
    monkeypatch.setattr(checkout_module, "resolve_ast_grep_binary", lambda repo_root: None)
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
    monkeypatch.setattr(checkout_module, "resolve_ast_grep_binary", lambda repo_root: "ast-grep")
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
    monkeypatch.setattr(checkout_module, "resolve_ast_grep_binary", lambda repo_root: "ast-grep")
    github = _StubGitHub(head_sha=head_sha, reviews=[])
    ctx = _ctx_for(repo, github, tmp_path, mode="Review", analyzers_mode="off")

    payload = await _checkout(ctx)

    assert "impactPath" not in payload
