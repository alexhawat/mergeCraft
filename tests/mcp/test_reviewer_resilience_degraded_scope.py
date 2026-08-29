"""Plan 13 W1.3 — degraded review scope RED contracts (green after W4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.mcp.reviewer_resilience_support import git_ctx, init_pr_clone, tool_error_text

from mergecraft.mcp.checkout import checkout_pr_tool
from mergecraft.mcp.commit_info import get_commit_info_tool
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
from mergecraft.mcp.verdict import ReviewPhase
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient


class _StubGitHub(GitHubClient):
    def __init__(self, *, head_sha: str, files: list[dict[str, Any]] | None = None) -> None:
        super().__init__(token="test-token")
        self._head_sha = head_sha
        self._files = files or [
            {"filename": "src/a.py", "patch": "@@ -0,0 +1 @@\n+line\n"},
        ]
        self.fetch_calls = 0

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        repo_ref = {"full_name": f"{owner}/{repo}"}
        return {
            "head": {"ref": "feature", "sha": self._head_sha, "repo": repo_ref},
            "base": {"ref": "main", "repo": repo_ref},
            "title": "PR",
            "html_url": "https://x/1",
        }

    async def get(self, path: str, **kwargs: Any) -> Any:
        if path.endswith("/files"):
            return self._files
        return {}

    async def get_commit(self, owner: str, repo: str, sha: str) -> dict[str, Any]:
        return {
            "sha": sha,
            "commit": {"message": "msg", "author": {"date": "2026-01-01T00:00:00Z"}},
            "author": {"login": "dev"},
            "committer": {"login": "dev"},
            "html_url": "https://x/c",
            "parents": [],
            "stats": {"additions": 1, "deletions": 0, "total": 1},
            "files": self._files,
        }


class _EmptyCommitFilesGitHub(_StubGitHub):
    async def get_commit(self, owner: str, repo: str, sha: str) -> dict[str, Any]:
        data = await super().get_commit(owner, repo, sha)
        data["files"] = []
        return data


def _ctx(tmp_path: Path, github: GitHubClient) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request_target")),
        github=github,
        github_installation_token="",
        git_token="token",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


@pytest.mark.asyncio
async def test_auth_head_fetch_yields_api_only_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    head_sha = "a" * 40
    github = _StubGitHub(head_sha=head_sha)

    def _auth_fail(*args: Any, **kwargs: Any) -> str:
        from mergecraft.mcp import git as git_mod

        raise RuntimeError(f"git fetch failed (401): HTTP/2 401\n{git_mod._AUTH_FAILURE_HINT}")

    monkeypatch.setattr("mergecraft.mcp.checkout._run_git", _auth_fail)
    monkeypatch.setattr("mergecraft.mcp.checkout.get_git_status", lambda cwd: "")

    ctx = _ctx(tmp_path, github)
    result = await checkout_pr_tool(ctx).execute({"pull_number": 546})
    assert result.is_error is False, result.content[0]["text"]
    payload = json.loads(result.content[0]["text"])
    assert payload["scope"] == "api-only"
    assert payload.get("diffPath")
    diff_path = payload["diffPath"]
    assert diff_path.endswith(".diff") or diff_path
    assert payload["reviewPhase"] == ReviewPhase.ESTABLISH_SCOPE.value
    assert ctx.tool_state.review_phase == ReviewPhase.ESTABLISH_SCOPE.value


@pytest.mark.asyncio
async def test_checkout_sha_from_api_when_local_ref_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    head_sha = "b" * 40
    github = _StubGitHub(head_sha=head_sha)

    def _fail_fetch(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("git fetch failed (128): could not read Username")

    monkeypatch.setattr("mergecraft.mcp.checkout._run_git", _fail_fetch)
    monkeypatch.setattr("mergecraft.mcp.checkout.get_git_status", lambda cwd: "")

    ctx = _ctx(tmp_path, github)
    payload = json.loads(
        (await checkout_pr_tool(ctx).execute({"pull_number": 1})).content[0]["text"]
    )
    assert payload["checkoutSha"] == head_sha
    assert primary_repo_state(ctx.tool_state).checkout_sha == head_sha


@pytest.mark.asyncio
async def test_degraded_scope_allows_terminal_approve(tmp_path: Path) -> None:
    from mergecraft.mcp.verdict import submit_review_verdict_tool

    ctx = _ctx(tmp_path, _StubGitHub(head_sha="c" * 40))
    primary = primary_repo_state(ctx.tool_state)
    primary.diff_path = str(tmp_path / "pr.diff")
    (tmp_path / "pr.diff").write_text("diff --git a/x b/x\n", encoding="utf-8")
    ctx.tool_state.review_phase = ReviewPhase.ESTABLISH_SCOPE.value
    ctx.tool_state.selected_mode = "Review"
    ctx.tool_state.pr_number = 1
    primary.issue_number = 1
    primary.checkout_sha = "c" * 40

    result = await submit_review_verdict_tool(ctx).execute(
        {
            "verdict": "approve",
            "summary": "Diff from API is complete; head-side reads unavailable.",
            "findings": [],
        }
    )
    assert result.is_error is False, result.content[0]["text"]


@pytest.mark.asyncio
async def test_degraded_payload_names_limitation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "mergecraft.mcp.checkout._run_git",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("auth failed (401)")),
    )
    monkeypatch.setattr("mergecraft.mcp.checkout.get_git_status", lambda cwd: "")

    payload = json.loads(
        (
            await checkout_pr_tool(_ctx(tmp_path, _StubGitHub(head_sha="d" * 40))).execute(
                {"pull_number": 1}
            )
        ).content[0]["text"]
    )
    degraded = payload.get("degraded") or payload.get("degradation")
    assert degraded
    assert "api" in str(degraded).lower() or "head" in str(degraded).lower()


@pytest.mark.asyncio
async def test_transient_fetch_retries_once_before_degrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def _flaky(*args: Any, **kwargs: Any) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("git fetch failed (500): server error")
        raise RuntimeError("still failing")

    monkeypatch.setattr("mergecraft.mcp.checkout._run_git", _flaky)
    monkeypatch.setattr("mergecraft.mcp.checkout.get_git_status", lambda cwd: "")

    await checkout_pr_tool(_ctx(tmp_path, _StubGitHub(head_sha="e" * 40))).execute(
        {"pull_number": 1}
    )
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_auth_class_fetch_does_not_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def _auth(*args: Any, **kwargs: Any) -> str:
        calls["n"] += 1
        raise RuntimeError("git fetch failed (403): forbidden")

    monkeypatch.setattr("mergecraft.mcp.checkout._run_git", _auth)
    monkeypatch.setattr("mergecraft.mcp.checkout.get_git_status", lambda cwd: "")

    await checkout_pr_tool(_ctx(tmp_path, _StubGitHub(head_sha="f" * 40))).execute(
        {"pull_number": 1}
    )
    assert calls["n"] == 1


def _establish_review_scope_tool(ctx: ToolContext):
    import importlib

    mod = importlib.import_module("mergecraft.mcp.verdict")
    factory = getattr(mod, "establish_review_scope_tool", None)
    assert factory is not None, "establish_review_scope_tool is not implemented yet"
    return factory(ctx)


@pytest.mark.asyncio
async def test_establish_review_scope_accepts_valid_diff(tmp_path: Path) -> None:
    head_sha = "1" * 40
    diff_path = tmp_path / "real.diff"
    diff_path.write_text("diff --git a/x b/x\n", encoding="utf-8")
    ctx = _ctx(tmp_path, _StubGitHub(head_sha=head_sha))
    ctx.tool_state.pr_number = 1

    result = await _establish_review_scope_tool(ctx).execute(
        {"diff_path": str(diff_path), "base_sha": "0" * 40, "head_sha": head_sha}
    )
    assert result.is_error is False, result.content[0]["text"]
    assert primary_repo_state(ctx.tool_state).diff_path == str(diff_path)


@pytest.mark.parametrize(
    "diff_text",
    ["", "not-a-diff"],
)
@pytest.mark.asyncio
async def test_establish_review_scope_refuses_invalid_diff(tmp_path: Path, diff_text: str) -> None:
    head_sha = "2" * 40
    diff_path = tmp_path / "bad.diff"
    if diff_text:
        diff_path.write_text(diff_text, encoding="utf-8")
    ctx = _ctx(tmp_path, _StubGitHub(head_sha=head_sha))
    ctx.tool_state.pr_number = 1

    result = await _establish_review_scope_tool(ctx).execute(
        {
            "diff_path": str(diff_path),
            "base_sha": "0" * 40,
            "head_sha": head_sha,
        }
    )
    assert result.is_error is True


@pytest.mark.asyncio
async def test_establish_review_scope_refuses_wrong_head_sha(tmp_path: Path) -> None:
    diff_path = tmp_path / "real.diff"
    diff_path.write_text("diff --git a/x b/x\n", encoding="utf-8")
    ctx = _ctx(tmp_path, _StubGitHub(head_sha="3" * 40))
    ctx.tool_state.pr_number = 1

    result = await _establish_review_scope_tool(ctx).execute(
        {"diff_path": str(diff_path), "base_sha": "0" * 40, "head_sha": "4" * 40}
    )
    assert result.is_error is True


@pytest.mark.parametrize("empty_files", [True, False], ids=["empty", "non-unified"])
@pytest.mark.asyncio
async def test_get_commit_info_invalid_diff_keeps_init_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    empty_files: bool,
) -> None:
    head_sha = "9" * 40
    github: GitHubClient = (
        _EmptyCommitFilesGitHub(head_sha=head_sha)
        if empty_files
        else _StubGitHub(head_sha=head_sha)
    )
    ctx = _ctx(tmp_path, github)
    ctx.tool_state.pr_number = 1
    primary = primary_repo_state(ctx.tool_state)
    primary.checkout_sha = head_sha
    ctx.tool_state.review_phase = "INIT"

    if not empty_files:
        original_write_text = Path.write_text

        def _write_text(self: Path, data: str, *args: Any, **kwargs: Any) -> int | None:
            if self.name.startswith("commit-") and self.suffix == ".diff":
                data = "not-a-diff"
            return original_write_text(self, data, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", _write_text)

    result = await get_commit_info_tool(ctx).execute({"sha": head_sha})
    text = tool_error_text(result)
    assert "unified diff" in text.lower() or "empty" in text.lower()
    assert ctx.tool_state.review_phase == "INIT"
    assert ctx.tool_state.scope_provenance is None
    assert primary.diff_path is None


@pytest.mark.asyncio
async def test_successful_checkout_pr_sets_scope_provenance_checkout(tmp_path: Path) -> None:
    clone, head_sha = init_pr_clone(tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    ctx = git_ctx(tmp_path, repo_dir=clone, github=_StubGitHub(head_sha=head_sha))
    ctx.tmpdir = str(artifacts)
    ctx.git_token = "token"

    result = await checkout_pr_tool(ctx).execute({"pull_number": 1})
    assert result.is_error is False, result.content[0]["text"]
    assert ctx.tool_state.scope_provenance == "checkout"
    assert ctx.tool_state.review_phase == ReviewPhase.ESTABLISH_SCOPE.value


@pytest.mark.asyncio
async def test_get_commit_info_registers_scope_for_pr_head(tmp_path: Path) -> None:
    head_sha = "5" * 40
    ctx = _ctx(tmp_path, _StubGitHub(head_sha=head_sha))
    ctx.tool_state.pr_number = 1
    primary = primary_repo_state(ctx.tool_state)
    primary.checkout_sha = head_sha

    result = await get_commit_info_tool(ctx).execute({"sha": head_sha})
    assert result.is_error is False, result.content[0]["text"]
    assert ctx.tool_state.review_phase == ReviewPhase.ESTABLISH_SCOPE.value
    assert primary.diff_path


@pytest.mark.asyncio
async def test_get_commit_info_does_not_register_scope_for_other_sha(tmp_path: Path) -> None:
    head_sha = "6" * 40
    ctx = _ctx(tmp_path, _StubGitHub(head_sha=head_sha))
    ctx.tool_state.pr_number = 1
    primary = primary_repo_state(ctx.tool_state)
    primary.checkout_sha = head_sha
    ctx.tool_state.review_phase = "INIT"

    await get_commit_info_tool(ctx).execute({"sha": "7" * 40})
    assert ctx.tool_state.review_phase == "INIT"
    assert primary.diff_path is None


@pytest.mark.asyncio
async def test_git_show_immutable_read_returns_cached_on_repeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.mcp.git import git_tool

    calls = {"n": 0}

    def _run(args: list[str], *, cwd: str, env: dict[str, str] | None = None) -> str:
        calls["n"] += 1
        return "file contents\n"

    monkeypatch.setattr("mergecraft.mcp.git._run_git", _run)
    ctx_tool = git_tool(_ctx(tmp_path, _StubGitHub(head_sha="8" * 40)))
    first = json.loads(
        (await ctx_tool.execute({"command": "show", "args": ["deadbeef:README.md"]})).content[0][
            "text"
        ]
    )
    second = json.loads(
        (await ctx_tool.execute({"command": "show", "args": ["deadbeef:README.md"]})).content[0][
            "text"
        ]
    )
    assert first["outputPath"] == second["outputPath"]
    assert second.get("cached") is True
    assert calls["n"] == 1
