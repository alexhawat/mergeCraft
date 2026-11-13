"""Integrity boundaries and Git confinement remain responsive under real RPC dispatch."""

from __future__ import annotations

import asyncio
import contextlib
import shlex
import sys
import threading
import time
from typing import TYPE_CHECKING, Any

import pytest
from tests.mcp.test_checkout import _ctx_for, _git, _pr_repo_with_two_commits, _StubGitHub
from tests.mcp.test_git_tool import _ctx as git_ctx
from tests.mcp.test_static_checks import _ctx as static_ctx
from tests.support.policy_fixtures import init_git_repo

from mergecraft.mcp.checkout import checkout_pr_tool
from mergecraft.mcp.git import git_tool
from mergecraft.mcp.rpc import dispatch_mcp_rpc
from mergecraft.mcp.static_checks import run_static_checks_tool
from mergecraft.review_checks import StaticCheckConfig
from mergecraft.security import review_integrity

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.shared import ToolSpec


async def _call(spec: ToolSpec, ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    return await dispatch_mcp_rpc(
        1,
        "tools/call",
        {"name": spec.name, "arguments": arguments},
        tools=[spec],
        by_name={spec.name: spec},
        tool_ctx=ctx,
        validators={},
    )


async def _list_tools_during_work(entered: threading.Event, finished: threading.Event) -> None:
    assert await asyncio.to_thread(entered.wait, 5), "blocking boundary was not reached"
    response = await dispatch_mcp_rpc(
        2, "tools/list", {}, tools=[], by_name={}, tool_ctx=None, validators={}
    )
    assert "error" not in response
    assert not finished.is_set(), "the integrity/confinement boundary blocked the RPC loop"


@pytest.mark.parametrize("tool_name", ["checkout", "static"])
@pytest.mark.parametrize("hash_index", [1, 2], ids=["before", "after"])
async def test_integrity_hashing_does_not_block_concurrent_rpc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool_name: str, hash_index: int
) -> None:
    if tool_name == "checkout":
        repo, _, sha = await asyncio.to_thread(_pr_repo_with_two_commits, tmp_path)
        ctx = _ctx_for(
            repo,
            _StubGitHub(head_sha=sha, reviews=[]),
            tmp_path,
            mode="Review",
            analyzers_mode="off",
        )
        spec, arguments = checkout_pr_tool(ctx), {"pull_number": 1}
    else:
        repo = tmp_path
        ctx = static_ctx(
            repo,
            static_checks=[
                StaticCheckConfig(name="gate", command=shlex.join([sys.executable, "-c", "pass"]))
            ],
        )
        spec, arguments = run_static_checks_tool(ctx), {}
    ctx.tool_state.review_tree_baseline = review_integrity.TreeBaseline(
        repo, review_integrity.hash_tree(repo)
    )
    entered, finished = threading.Event(), threading.Event()
    original_hash = review_integrity.hash_tree
    calls = 0

    def slow_hash(root: Path) -> str:
        nonlocal calls
        calls += 1
        if calls == hash_index:
            entered.set()
            time.sleep(0.2)
            finished.set()
        return original_hash(root)

    monkeypatch.setattr(review_integrity, "hash_tree", slow_hash)
    pending = asyncio.create_task(_call(spec, ctx, arguments))
    try:
        await _list_tools_during_work(entered, finished)
    finally:
        response = await pending
    assert "error" not in response
    ctx.tool_state.review_tree_baseline.verify()


async def test_git_subdirectory_confinement_does_not_block_concurrent_rpc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.mcp import git as git_module

    await asyncio.to_thread(init_git_repo, tmp_path)
    subdir = tmp_path / "subdirectory"
    subdir.mkdir()
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    ctx = git_ctx(tmp_path)
    spec = git_tool(ctx)
    entered, finished = threading.Event(), threading.Event()
    original = git_module.absolute_git_dir

    def slow_discovery(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        time.sleep(0.2)
        result = original(*args, **kwargs)
        finished.set()
        return result

    monkeypatch.setattr(git_module, "absolute_git_dir", slow_discovery)
    pending = asyncio.create_task(
        _call(spec, ctx, {"command": "git", "args": ["-C", str(subdir), "status", "--porcelain"]})
    )
    try:
        await _list_tools_during_work(entered, finished)
    finally:
        response = await pending
    assert "error" not in response


@pytest.mark.parametrize("integrity_state", ["clean", "already-broken", "tampered"])
async def test_cancelled_checkout_repins_tree_after_worker_changed_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, integrity_state: str
) -> None:
    from mergecraft.mcp import checkout as checkout_module
    from mergecraft.mcp.tool_state import primary_repo_state

    repo, _, sha = await asyncio.to_thread(_pr_repo_with_two_commits, tmp_path)
    await asyncio.to_thread(_git, repo, "checkout", "base")
    ctx = _ctx_for(
        repo,
        _StubGitHub(head_sha=sha, reviews=[]),
        tmp_path,
        mode="Review",
        analyzers_mode="off",
    )
    from mergecraft.config.settings_snapshot import capture_repo_settings_snapshot

    prior_settings = capture_repo_settings_snapshot(root=repo, operator_owned=True)
    ctx.repo_settings_snapshot = prior_settings
    baseline = review_integrity.TreeBaseline(
        repo, review_integrity.hash_tree(repo), broken=integrity_state == "already-broken"
    )
    original_digest = baseline.digest
    if integrity_state == "tampered":
        (repo / ".git" / "info" / "exclude").write_text("ignored-proof\n")
        (repo / "ignored-proof").write_text("unauthorized agent edit")
    ctx.tool_state.review_tree_baseline = baseline
    changed, release = threading.Event(), threading.Event()
    original = checkout_module._run_git

    def delayed_checkout(args: list[str], **kwargs: Any) -> str:
        result = original(args, **kwargs)
        if args[:2] == ["checkout", "-B"]:
            changed.set()
            assert release.wait(5)
        return result

    monkeypatch.setattr(checkout_module, "_run_git", delayed_checkout)
    pending = asyncio.create_task(_call(checkout_pr_tool(ctx), ctx, {"pull_number": 1}))
    try:
        assert await asyncio.to_thread(changed.wait, 5)
        pending.cancel()
        await asyncio.sleep(0.05)
        assert not pending.done(), "checkout cleanup abandoned its worker"
    finally:
        release.set()
        with contextlib.suppress(asyncio.CancelledError):
            await pending
    assert pending.cancelled()
    assert ctx.tool_state.checkout_scope_invalidated
    assert primary_repo_state(ctx.tool_state).checkout_sha is None
    assert (repo / "new.py").exists(), "the authorized checkout did not change the tree"
    assert ctx.repo_settings_snapshot is not None
    assert ctx.repo_settings_snapshot.settings is prior_settings.settings
    assert ctx.repo_settings_snapshot.operator_owned
    if integrity_state == "clean":
        baseline.verify()
    else:
        assert baseline.broken
        assert baseline.digest == original_digest
        with pytest.raises(RuntimeError, match="checkout integrity failure"):
            baseline.verify()


async def test_cancelled_static_gate_finishes_queued_integrity_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from mergecraft.mcp import static_checks as static_module

    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
    command = shlex.join(
        [sys.executable, "-c", "from pathlib import Path; Path('generated.txt').write_text('gate')"]
    )
    ctx = static_ctx(tmp_path, static_checks=[StaticCheckConfig(name="gate", command=command)])
    baseline = review_integrity.TreeBaseline(tmp_path, review_integrity.hash_tree(tmp_path))
    ctx.tool_state.review_tree_baseline = baseline
    blocker_started = asyncio.Event()
    release_blocker, submitted = threading.Event(), threading.Event()
    siblings: list[asyncio.Future[None]] = []
    original_checks = static_module.run_checks

    def blocker() -> None:
        loop.call_soon_threadsafe(blocker_started.set)
        assert release_blocker.wait(5)

    def submit_blocker() -> None:
        siblings.append(loop.run_in_executor(None, blocker))
        submitted.set()

    def checks_then_saturate(*args: Any, **kwargs: Any) -> Any:
        result = original_checks(*args, **kwargs)
        loop.call_soon_threadsafe(submit_blocker)
        assert submitted.wait(5)
        return result

    monkeypatch.setattr(static_module, "run_checks", checks_then_saturate)
    pending = asyncio.create_task(_call(run_static_checks_tool(ctx), ctx, {}))
    try:
        await asyncio.wait_for(blocker_started.wait(), timeout=5)
        await asyncio.sleep(0.02)
        pending.cancel()
        await asyncio.sleep(0)
        pending.cancel()
        done, _ = await asyncio.wait({pending}, timeout=0.2)
        assert not done, "cancellation skipped the required post-gate integrity re-pin"
        assert ctx.tool_state.checkout_operation_lock.locked()
    finally:
        release_blocker.set()
        with contextlib.suppress(asyncio.CancelledError):
            await pending
        await asyncio.gather(*siblings)
    assert pending.cancelled()
    assert (tmp_path / "generated.txt").read_text() == "gate"
    baseline.verify()


async def test_publication_during_precheckout_hash_must_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.mcp.git import _run_git
    from mergecraft.mcp.tool_state import ReviewRecord, primary_repo_state

    repo, _, sha = await asyncio.to_thread(_pr_repo_with_two_commits, tmp_path)
    await asyncio.to_thread(_git, repo, "checkout", "base")
    before = await asyncio.to_thread(_run_git, ["rev-parse", "HEAD"], cwd=str(repo))
    ctx = _ctx_for(
        repo, _StubGitHub(head_sha=sha, reviews=[]), tmp_path, mode="Review", analyzers_mode="off"
    )
    ctx.tool_state.review_tree_baseline = review_integrity.TreeBaseline(
        repo, review_integrity.hash_tree(repo)
    )
    entered, release = threading.Event(), threading.Event()
    original = review_integrity.hash_tree

    def delayed_hash(root: Path) -> str:
        entered.set()
        assert release.wait(5)
        return original(root)

    monkeypatch.setattr(review_integrity, "hash_tree", delayed_hash)
    pending = asyncio.create_task(checkout_pr_tool(ctx).execute({"pull_number": 1}))
    receipt = ReviewRecord(id=1, node_id="R1", reviewed_sha=before.strip(), verdict="approve")
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        ctx.tool_state.review = receipt
    finally:
        release.set()
        result = await pending
    after = await asyncio.to_thread(_run_git, ["rev-parse", "HEAD"], cwd=str(repo))
    assert result.is_error, (
        before.strip(),
        after.strip(),
        primary_repo_state(ctx.tool_state).checkout_sha,
    )
    assert "published a review" in str(result.content)
    assert ctx.tool_state.review is receipt
    assert not ctx.tool_state.checkout_scope_invalidated
    assert after == before
