"""W1.5-9 — ``git_fetch`` depth, api-only analyzer scope and base-fetch reporting.

Every case runs the production tool against real temporary git repositories
(full and shallow clones); only the GitHub API is stubbed.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any

import pytest
from tests.mcp.test_checkout_degraded_diff import (
    _checkout,
    _ctx_for,
    _pr_repo,
    _StubGitHub,
)
from tests.mcp.test_git_tool import _ctx

from mergecraft.mcp import checkout as checkout_module
from mergecraft.mcp.analyzers import run_analyzers_tool
from mergecraft.mcp.git import git_fetch_tool
from mergecraft.mcp.tool_state import primary_repo_state

if TYPE_CHECKING:
    from pathlib import Path


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _origin_with_history(tmp_path: Path, commits: int = 4) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    for i in range(commits):
        (work / "f.txt").write_text(f"{i}\n", encoding="utf-8")
        _git(work, "add", "f.txt")
        _git(work, "commit", "-q", "-m", f"c{i}")
    bare = tmp_path / "origin.git"
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(bare))
    return bare


def _clone(tmp_path: Path, bare: Path, name: str, *extra: str) -> Path:
    dest = tmp_path / name
    # file:// so --depth is honoured for a local path.
    _git(tmp_path, "clone", "-q", *extra, f"file://{bare}", str(dest))
    return dest


def _count(repo: Path) -> int:
    return int(_git(repo, "rev-list", "--count", "HEAD"))


@pytest.fixture(autouse=True)
def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))


async def test_depth_on_a_full_clone_is_refused_and_history_survives(tmp_path: Path) -> None:
    clone = _clone(tmp_path, _origin_with_history(tmp_path), "full")
    before = _count(clone)

    result = await git_fetch_tool(_ctx(clone)).execute({"depth": 1})

    assert result.is_error is True
    assert "full clone" in result.content[0]["text"]
    assert _git(clone, "rev-parse", "--is-shallow-repository") == "false"
    assert not (clone / ".git" / "shallow").exists()
    assert _count(clone) == before == 4


async def test_depth_on_a_shallow_clone_is_forwarded(tmp_path: Path) -> None:
    clone = _clone(tmp_path, _origin_with_history(tmp_path), "shallow", "--depth", "1")
    assert _count(clone) == 1

    result = await git_fetch_tool(_ctx(clone)).execute({"depth": 2})

    assert result.is_error is not True, result.content[0]["text"]
    assert _git(clone, "rev-parse", "--is-shallow-repository") == "true"
    assert _count(clone) == 2


async def test_deepen_on_a_shallow_clone_adds_history(tmp_path: Path) -> None:
    clone = _clone(tmp_path, _origin_with_history(tmp_path), "shallow", "--depth", "1")

    result = await git_fetch_tool(_ctx(clone)).execute({"deepen": 2})

    assert result.is_error is not True, result.content[0]["text"]
    assert _count(clone) == 3


@pytest.mark.parametrize(
    "bad",
    [0, -1, 1.5, "3", True],
    ids=["zero", "negative", "fractional", "string", "bool"],
)
@pytest.mark.parametrize("key", ["depth", "deepen"])
async def test_non_positive_integer_counts_are_refused(tmp_path: Path, key: str, bad: Any) -> None:
    clone = _clone(tmp_path, _origin_with_history(tmp_path), "shallow", "--depth", "1")

    result = await git_fetch_tool(_ctx(clone)).execute({key: bad})

    assert result.is_error is True
    assert "whole number" in result.content[0]["text"]
    assert _count(clone) == 1


def test_schema_declares_positive_integers(tmp_path: Path) -> None:
    props = git_fetch_tool(_ctx(tmp_path)).input_schema["properties"]
    for key in ("depth", "deepen"):
        assert props[key]["type"] == "integer"
        assert props[key]["minimum"] == 1


async def test_api_only_scope_skips_local_analyzers_with_a_named_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _pr_repo(tmp_path)
    # No refs/pull/2/head on the remote, so the head fetch fails for real and the
    # checkout registers api-only scope.
    ctx = _ctx_for(repo, _StubGitHub(), tmp_path)
    monkeypatch.setattr(
        checkout_module, "_fetch_head_with_retry", lambda **_k: (False, "no such ref")
    )

    is_error, payload = await _checkout(ctx)

    assert is_error is False, payload
    assert isinstance(payload, dict)
    assert payload["scope"] == "api-only"

    result = await run_analyzers_tool(ctx).execute({})

    body = json.loads(result.content[0]["text"])
    assert body["ran"] is False
    assert "head not materialized" in body["reason"]
    assert body["findingCount"] == 0
    recorded = ctx.tool_state.analyzer_run
    assert recorded is not None
    assert recorded.ran is False
    assert "head not materialized" in str(recorded.reason)
    from mergecraft.mcp.verification import _deterministic_checks_ran

    assert _deterministic_checks_ran(ctx) == ["run_analyzers"]


async def test_failed_base_fetch_is_reported_when_the_local_diff_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _pr_repo(tmp_path)
    real = checkout_module._run_git

    def _fail_base_fetch(args: list[str], **kwargs: Any) -> str:
        if args[:1] == ["fetch"] and any("refs/remotes/origin/base" in a for a in args):
            msg = "fatal: unable to access remote"
            raise RuntimeError(msg)
        return real(args, **kwargs)

    monkeypatch.setattr(checkout_module, "_run_git", _fail_base_fetch)
    ctx = _ctx_for(repo, _StubGitHub(), tmp_path)

    is_error, payload = await _checkout(ctx)

    assert is_error is False, payload
    assert isinstance(payload, dict)
    assert ctx.tool_state.scope_provenance == "checkout"
    assert "unable to access remote" in payload["degraded"]
    assert "stale" in payload["degraded"]


async def test_successful_base_fetch_records_no_degradation(tmp_path: Path) -> None:
    repo = _pr_repo(tmp_path)
    ctx = _ctx_for(repo, _StubGitHub(), tmp_path)

    is_error, payload = await _checkout(ctx)

    assert is_error is False, payload
    assert isinstance(payload, dict)
    assert "degraded" not in payload


def _deepen_base(tmp_path: Path, clone: Path, extra: int = 1100) -> None:
    """Put more than 1000 commits on origin's ``base`` and fetch them in full."""
    work = tmp_path / "work"
    head = "from refs/heads/base^0\n"
    body = "".join(
        f"commit refs/heads/base\ncommitter T <t@example.com> {1700000001 + i} +0000\n"
        f"data 1\nx\n{head if i == 0 else ''}\n"
        for i in range(extra)
    )
    subprocess.run(
        ["git", "fast-import", "--quiet"],
        cwd=work,
        input=body,
        text=True,
        check=True,
    )
    _git(work, "push", "-q", str(tmp_path / "origin.git"), "base:refs/heads/base")
    _git(clone, "fetch", "-q", "origin", "base:refs/remotes/origin/base")


def _shallow_flag(repo: Path) -> str:
    return _git(repo, "rev-parse", "--is-shallow-repository")


async def test_checkout_pr_keeps_a_full_clone_full(tmp_path: Path) -> None:
    repo = _pr_repo(tmp_path)
    _deepen_base(tmp_path, repo)
    assert _shallow_flag(repo) == "false"
    # A URL remote, as in production: a plain path would ignore --depth.
    _git(repo, "remote", "set-url", "origin", f"file://{_git(repo, 'remote', 'get-url', 'origin')}")
    ctx = _ctx_for(repo, _StubGitHub(), tmp_path)

    is_error, payload = await _checkout(ctx)

    assert is_error is False, payload
    assert _shallow_flag(repo) == "false"
    assert not (repo / ".git" / "shallow").exists()


async def test_checkout_pr_keeps_a_shallow_clone_working(tmp_path: Path) -> None:
    full = _pr_repo(tmp_path)
    shallow = tmp_path / "shallow"
    origin = _git(full, "remote", "get-url", "origin")
    _git(tmp_path, "clone", "-q", "--depth", "1", f"file://{origin}", str(shallow))
    assert _shallow_flag(shallow) == "true"
    github = _StubGitHub()
    ctx = _ctx_for(full, github, tmp_path)
    primary_repo_state(ctx.tool_state).dir = str(shallow)

    is_error, payload = await _checkout(ctx)

    assert is_error is False, payload
    assert _shallow_flag(shallow) == "true"
