"""Real MCP dispatch stays responsive and cancels timed-out tool work."""

from __future__ import annotations

import asyncio
import contextlib
import json
import shlex
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from tests.mcp.test_static_checks import _ctx
from tests.support.tool_context import inner_mutation_guard_probe

from mergecraft.mcp.rpc import dispatch_mcp_rpc
from mergecraft.mcp.shared import ToolClass, ToolSpec
from mergecraft.mcp.static_checks import run_static_checks_tool
from mergecraft.review_checks import StaticCheckConfig


def _wait_for_file(path: Path) -> None:
    deadline = time.monotonic() + 5
    while not path.exists():
        if time.monotonic() >= deadline:
            raise AssertionError(f"child did not create {path.name}")
        time.sleep(0.005)


async def _dispatch(spec: ToolSpec, *, ctx: Any = None) -> dict[str, Any]:
    return await dispatch_mcp_rpc(
        1,
        "tools/call",
        {"name": spec.name, "arguments": {}},
        tools=[spec],
        by_name={spec.name: spec},
        tool_ctx=ctx,
        validators={},
    )


async def test_rpc_deadline_cancels_coroutine_before_result_publication() -> None:
    cancelled = asyncio.Event()
    completed = asyncio.Event()

    async def slow(_params: Any) -> dict[str, str]:
        try:
            await asyncio.sleep(0.2)
            completed.set()
            return {"status": "late"}
        finally:
            cancelled.set()

    spec = ToolSpec("slow", "slow", {"type": "object"}, slow, ToolClass.ANALYSIS, timeout_ms=10)
    result = await _dispatch(spec)
    assert result["error"]["code"] == -32000
    assert "timed out" in result["error"]["message"]
    assert cancelled.is_set()
    assert not completed.is_set()


async def test_shell_rpc_returns_partial_output_after_max_command_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.mcp import shell

    # Use the real shell process and dispatch on a short command budget.
    monkeypatch.setattr(shell, "_MAX_COMMAND_TIMEOUT_MS", 300)
    monkeypatch.setattr(shell, "_RPC_CLEANUP_HEADROOM_MS", 2_000)
    monkeypatch.setattr(shell, "detect_sandbox_method", lambda: "none")
    monkeypatch.setenv("MERGECRAFT_ALLOW_UNSANDBOXED_SHELL", "1")
    ctx = _ctx(tmp_path)
    spec = shell.shell_tool(ctx)
    command = "printf 'partial output\n'; sleep 3"
    with inner_mutation_guard_probe():
        response = await dispatch_mcp_rpc(
            1,
            "tools/call",
            {
                "name": spec.name,
                "arguments": {
                    "command": command,
                    "description": "deadline test",
                    "timeout": 120_000,
                },
            },
            tools=[spec],
            by_name={spec.name: spec},
            tool_ctx=ctx,
            validators={},
        )
    assert "result" in response, response
    result = json.loads(response["result"]["content"][0]["text"])
    assert result["timed_out"] is True
    assert result["exit_code"] != 0
    assert result["output"] == "partial output\n[timed out after 300ms]"


def _gate(tmp_path: Path, *, delay: float = 0.6) -> ToolSpec:
    script = tmp_path / "gate.py"
    script.write_text(
        "import os,time\nfrom pathlib import Path\n"
        "Path('started').write_text(str(os.getpid()))\n"
        f"time.sleep({delay})\nPath('finished').write_text('done')\n"
    )
    config = StaticCheckConfig(name="slow", command=shlex.join([sys.executable, str(script)]))
    ctx = _ctx(tmp_path, static_checks=[config])
    return run_static_checks_tool(ctx)


async def test_real_static_gate_does_not_block_another_rpc(tmp_path: Path) -> None:
    spec = _gate(tmp_path)
    pending = asyncio.create_task(_dispatch(spec))
    try:
        await asyncio.to_thread(_wait_for_file, tmp_path / "started")

        async def fast(_params: Any) -> dict[str, bool]:
            return {"ready": True}

        fast_spec = ToolSpec("fast", "fast", {"type": "object"}, fast, ToolClass.ANALYSIS)
        listing = await _dispatch(fast_spec)
        assert json.loads(listing["result"]["content"][0]["text"])["ready"]
        assert not (tmp_path / "finished").exists(), "the slow gate monopolized the MCP loop"
    finally:
        await pending


async def test_real_static_gate_timeout_reaps_child_and_prevents_late_writes(
    tmp_path: Path,
) -> None:
    spec = _gate(tmp_path)
    spec.timeout_ms = 150
    result = await _dispatch(spec)
    assert result["error"]["code"] == -32000
    assert "timed out" in result["error"]["message"]
    assert (tmp_path / "started").exists()
    assert not (tmp_path / "finished").exists()
    pid = int((tmp_path / "started").read_text())
    import os

    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


async def test_outer_cancellation_is_not_reported_as_tool_timeout() -> None:
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def slow(_params: Any) -> dict[str, str]:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return {}

    spec = ToolSpec("slow", "slow", {"type": "object"}, slow, ToolClass.ANALYSIS, timeout_ms=5000)
    pending = asyncio.create_task(_dispatch(spec))
    await entered.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert cancelled.is_set()


async def test_checkout_fetch_yields_and_cancellation_invalidates_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os
    import shutil

    from tests.mcp.test_checkout import _ctx_for, _pr_repo_with_two_commits, _StubGitHub

    from mergecraft.mcp.checkout import checkout_pr_tool
    from mergecraft.mcp.tool_state import primary_repo_state

    repo, _, sha = await asyncio.to_thread(_pr_repo_with_two_commits, tmp_path)
    ctx = _ctx_for(
        repo, _StubGitHub(head_sha=sha, reviews=[]), tmp_path, mode="Review", analyzers_mode="off"
    )
    real_git = shutil.which("git")
    assert real_git is not None
    bindir = tmp_path / "bin"
    bindir.mkdir()
    wrapper = bindir / "git"
    started, finished = tmp_path / "fetch-started", tmp_path / "fetch-finished"
    wrapper.write_text(
        f"#!{sys.executable}\nimport os,sys,time\nfrom pathlib import Path\n"
        f"if 'fetch' in sys.argv:\n    Path({str(started)!r}).write_text(str(os.getpid()))\n"
        f"    time.sleep(0.6)\n    Path({str(finished)!r}).write_text('done')\n"
        f"os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])\n"
    )
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    spec = checkout_pr_tool(ctx)
    pending = asyncio.create_task(
        dispatch_mcp_rpc(
            1,
            "tools/call",
            {"name": spec.name, "arguments": {"pull_number": 1}},
            tools=[spec],
            by_name={spec.name: spec},
            tool_ctx=ctx,
            validators={},
        )
    )
    try:
        await asyncio.to_thread(_wait_for_file, started)
        await dispatch_mcp_rpc(
            2,
            "tools/list",
            {},
            tools=[spec],
            by_name={spec.name: spec},
            tool_ctx=ctx,
            validators={},
        )
        assert not finished.exists(), "fetch blocked the shared MCP event loop"
    finally:
        pending.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pending
    assert pending.cancelled()
    assert ctx.tool_state.checkout_scope_invalidated
    assert primary_repo_state(ctx.tool_state).checkout_sha is None
    with pytest.raises(ProcessLookupError):
        os.kill(int(started.read_text()), 0)
    assert not finished.exists()


async def test_cancelled_worker_finishes_before_state_can_be_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from tests.mcp.test_analyzers import _ctx as analyzer_ctx

    from mergecraft.mcp.analyzers import run_analyzers_tool
    from mergecraft.mcp.tool_state import AnalyzerRunState

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def bounded_io(**kwargs: Any) -> AnalyzerRunState:
        entered.set()
        assert release.wait(5)
        finished.set()
        return AnalyzerRunState(ran=True, reason="late result")

    monkeypatch.setattr("mergecraft.analyzers.pipeline.run_analyzer_pipeline", bounded_io)
    ctx = analyzer_ctx(tmp_path)
    spec = run_analyzers_tool(ctx)
    spec.timeout_ms = 50
    pending = asyncio.create_task(_dispatch(spec, ctx=ctx))
    assert await asyncio.to_thread(entered.wait, 5)
    try:
        await asyncio.sleep(0.1)
        assert not pending.done(), "cleanup must finish before shared state is reused"
        assert ctx.tool_state.analyzer_run is None
    finally:
        release.set()
    response = await pending
    assert response["error"]["code"] == -32000
    assert finished.is_set()
    assert ctx.tool_state.analyzer_run is None


async def test_concurrent_analyzer_calls_keep_distinct_scratch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from tests.mcp.test_analyzers import _ctx as analyzer_ctx

    from mergecraft.analyzers.sandbox import fresh_analyzer_scratch_dir
    from mergecraft.mcp.analyzers import run_analyzers_tool
    from mergecraft.mcp.tool_state import AnalyzerRunState

    first_ready, second_ready = threading.Event(), threading.Event()

    def pipeline(*, repo_root: Path, **kwargs: Any) -> AnalyzerRunState:
        if repo_root.name == "second":
            assert first_ready.wait(5)
        scratch = fresh_analyzer_scratch_dir("same-analyzer")
        marker = scratch / repo_root.name
        marker.write_text("owned")
        if repo_root.name == "first":
            first_ready.set()
            assert second_ready.wait(5)
        else:
            second_ready.set()
        assert marker.read_text() == "owned", "another call removed this run's scratch"
        return AnalyzerRunState(ran=False, reason="scratch checked")

    monkeypatch.setattr("mergecraft.analyzers.pipeline.run_analyzer_pipeline", pipeline)
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    results = await asyncio.gather(
        run_analyzers_tool(analyzer_ctx(first)).execute({}),
        run_analyzers_tool(analyzer_ctx(second)).execute({}),
    )
    assert all(not result.is_error for result in results), results


async def test_deadline_cancels_wait_for_analyzer_cache_lock(tmp_path: Path) -> None:
    import fcntl

    from mergecraft.analyzers.provision import _PROVISION_LOCK_NAME, cache_provision_lock
    from mergecraft.utils.blocking import run_blocking

    acquired: list[bool] = []

    def provision() -> None:
        with cache_provision_lock(tmp_path):
            acquired.append(True)

    async def slow(_params: Any) -> dict[str, str]:
        await run_blocking(provision)
        return {}

    spec = ToolSpec("slow", "slow", {"type": "object"}, slow, ToolClass.ANALYSIS, timeout_ms=50)
    with (tmp_path / _PROVISION_LOCK_NAME).open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pending = asyncio.create_task(_dispatch(spec))
        try:
            await asyncio.sleep(0.3)
            assert pending.done(), "cancelled provisioning waited indefinitely for a cache lock"
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            response = await pending
    assert response["error"]["code"] == -32000
    assert not acquired


async def test_same_context_analyzer_operations_wait_for_prior_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from tests.mcp.test_analyzers import _ctx as analyzer_ctx

    from mergecraft.mcp.analyzers import run_analyzers_tool
    from mergecraft.mcp.tool_state import AnalyzerRunState

    entered, release = threading.Event(), threading.Event()
    calls: list[bool] = []

    def pipeline(**kwargs: Any) -> AnalyzerRunState:
        calls.append(True)
        entered.set()
        assert release.wait(5)
        return AnalyzerRunState(ran=False, reason="done")

    monkeypatch.setattr("mergecraft.analyzers.pipeline.run_analyzer_pipeline", pipeline)
    ctx = analyzer_ctx(tmp_path)
    first = asyncio.create_task(run_analyzers_tool(ctx).execute({}))
    assert await asyncio.to_thread(entered.wait, 5)
    second = asyncio.create_task(run_analyzers_tool(ctx).execute({}))
    try:
        await asyncio.sleep(0.05)
        assert len(calls) == 1, "same-checkout operations ran concurrently"
        first.cancel()
        await asyncio.sleep(0.05)
        assert len(calls) == 1, "next operation started before cancellation cleanup"
    finally:
        release.set()
        first.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await first
        await second
    assert len(calls) == 2


async def test_base_settings_git_reads_do_not_block_rpc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from tests.analyzers.test_analyzer_settings_pinning import _ctx as pin_ctx
    from tests.analyzers.test_analyzer_settings_pinning import _pr_checkout

    from mergecraft.analyzers import settings_pin
    from mergecraft.mcp.analyzers import run_analyzers_tool
    from mergecraft.mcp.tool_state import AnalyzerRunState

    repo, sha = await asyncio.to_thread(_pr_checkout, tmp_path)
    entered, finished = threading.Event(), threading.Event()
    original = settings_pin._git

    def slow_git(root: Path, *args: str) -> Any:
        entered.set()
        time.sleep(0.15)
        result = original(root, *args)
        finished.set()
        return result

    monkeypatch.setattr(settings_pin, "_git", slow_git)
    monkeypatch.setattr(
        "mergecraft.analyzers.pipeline.run_analyzer_pipeline",
        lambda **kwargs: AnalyzerRunState(ran=False, reason="done"),
    )
    spec = run_analyzers_tool(pin_ctx(repo, base_sha=sha))
    pending = asyncio.create_task(_dispatch(spec))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        await dispatch_mcp_rpc(
            2, "ping", {}, tools=[spec], by_name={spec.name: spec}, tool_ctx=None, validators={}
        )
        assert not finished.is_set(), "base-settings Git reads blocked the RPC loop"
    finally:
        await pending


async def test_deadline_cleanup_does_not_queue_behind_saturated_workers(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
    spec = _gate(tmp_path, delay=2)
    spec.timeout_ms = 300
    pending = asyncio.create_task(_dispatch(spec))
    try:
        await asyncio.sleep(0.8)
        assert (tmp_path / "started").exists()
        assert pending.done(), "process cleanup queued behind the blocked worker"
    finally:
        response = await pending
    assert response["error"]["code"] == -32000
    assert not (tmp_path / "finished").exists()


async def test_queued_deadline_does_not_wait_for_an_unrelated_worker() -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from mergecraft.utils.blocking import run_blocking

    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
    sibling_started, release_sibling = asyncio.Event(), threading.Event()
    ran: list[bool] = []

    def sibling_work() -> None:
        loop.call_soon_threadsafe(sibling_started.set)
        assert release_sibling.wait(5)

    async def queued(_params: Any) -> dict[str, Any]:
        await run_blocking(lambda: ran.append(True))
        return {}

    sibling = asyncio.create_task(run_blocking(sibling_work))
    await asyncio.wait_for(sibling_started.wait(), timeout=5)
    spec = ToolSpec(
        "queued", "queued", {"type": "object"}, queued, ToolClass.ANALYSIS, timeout_ms=30
    )
    pending = asyncio.create_task(_dispatch(spec))
    try:
        done, _ = await asyncio.wait({pending}, timeout=0.5)
        assert done, "queued cancellation waited for an unrelated executor worker"
        assert not sibling.done()
        assert not ran
    finally:
        release_sibling.set()
        await sibling
        result = await pending
    assert result["error"]["code"] == -32000
    assert not ran, "cancelled queued work started after its timeout response"


@pytest.mark.parametrize("started_before_cancel", [False, True], ids=["queued", "running"])
async def test_repeated_cancellation_joins_only_started_work(started_before_cancel: bool) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from mergecraft.utils.blocking import run_blocking

    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
    sibling_started, release_sibling = asyncio.Event(), threading.Event()
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    work_started = asyncio.Event()
    published: list[bool] = []

    def sibling_work() -> None:
        loop.call_soon_threadsafe(sibling_started.set)
        assert release_sibling.wait(5)

    def work() -> None:
        started.set()
        loop.call_soon_threadsafe(work_started.set)
        assert release.wait(5)
        finished.set()

    async def operation() -> None:
        await run_blocking(work)
        published.append(True)

    sibling = None
    if not started_before_cancel:
        sibling = asyncio.create_task(run_blocking(sibling_work))
        await asyncio.wait_for(sibling_started.wait(), timeout=5)
    pending = asyncio.create_task(operation())
    if started_before_cancel:
        await asyncio.wait_for(work_started.wait(), timeout=5)
    else:
        await asyncio.sleep(0.02)
    try:
        pending.cancel()
        await asyncio.sleep(0)
        pending.cancel()
        done, _ = await asyncio.wait({pending}, timeout=0.3)
        if started_before_cancel:
            assert not done, "cancellation detached the already-running worker"
            assert not finished.is_set()
        else:
            assert done, "repeated queued cancellation waited for a sibling"
            assert not started.is_set()
    finally:
        release.set()
        release_sibling.set()
        if sibling is not None:
            await sibling
        with contextlib.suppress(asyncio.CancelledError):
            await pending
    assert pending.cancelled()
    assert not published
    assert started.is_set() is started_before_cancel
    assert finished.is_set() is started_before_cancel
