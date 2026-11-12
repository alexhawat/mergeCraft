"""Failure inputs x expected chain failover, for every CLI backend (#1328).

Each case drives the real driver read loop with a fake child (its stderr and
exit code are the input) and then asks the real chain predicate whether the
failed attempt may hand the review to the next model. The expectation is the
same for every backend: provider outages, transport errors, rate limits and
stalls fail over; unrelated text that merely contains a status-like number
does not.
"""

from __future__ import annotations

import importlib
import io
import threading
from typing import TYPE_CHECKING, Any, NamedTuple

import httpx
import pytest
from tests.agents.conftest import make_agent_run_context

from mergecraft.agents.post_run import run_post_run_retry_loop
from mergecraft.agents.shared import AgentResult, agent
from mergecraft.utils.agent_resolve import _may_advance_chain

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


class _FakeProcess:
    def __init__(self, *, stdout: Any, stderr: str, returncode: int, pid: int = 987654) -> None:
        self.stdout = stdout
        self.stderr = io.StringIO(stderr)
        self.pid = pid
        self._returncode = returncode

    def wait(self, timeout: float | None = None) -> int:
        return self._returncode

    def poll(self) -> int:
        return self._returncode


class _StallingStream:
    def __init__(self, stop: threading.Event) -> None:
        self._stop = stop

    def __iter__(self) -> _StallingStream:
        return self

    def __next__(self) -> str:
        self._stop.wait(5.0)
        raise StopIteration


class _Backend(NamedTuple):
    name: str
    module_name: str
    invoke: Callable[[Any, Any, Path], AgentResult]


def _claude(module: Any, ctx: Any, tmp_path: Path) -> AgentResult:
    return module._run_claude_once(
        cli="/usr/bin/claude", prompt="review", ctx=ctx, mcp_config=str(tmp_path / "mcp.json")
    )


def _codex(module: Any, ctx: Any, _tmp_path: Path) -> AgentResult:
    return module._run_codex_streaming(
        cmd=["codex", "exec"], ctx=ctx, model="gpt-5.6-sol", prompt="review"
    )


def _gemini(module: Any, ctx: Any, _tmp_path: Path) -> AgentResult:
    return module._run_gemini_streaming(
        cmd=["gemini", "-p"], ctx=ctx, model="gemini-3.1-pro", prompt="review"
    )


def _opencode(module: Any, ctx: Any, _tmp_path: Path) -> AgentResult:
    return module._run_opencode_cli_streaming(cmd=["opencode", "run"], ctx=ctx, env={})


_BACKENDS = (
    _Backend("claude", "mergecraft.agents.claude", _claude),
    _Backend("codex", "mergecraft.agents.codex", _codex),
    _Backend("gemini", "mergecraft.agents.gemini", _gemini),
    _Backend("opencode", "mergecraft.agents.opencode", _opencode),
)
_BACKEND_IDS = [backend.name for backend in _BACKENDS]

# (case id, stderr, exit code, may the chain advance?)
_FAILURES = (
    ("api-500", "API Error: 500 Internal server error", 1, True),
    ("http-503", "HTTP 503 Service Unavailable", 1, True),
    ("bad-gateway", "upstream returned 502 Bad Gateway", 1, True),
    ("connection-error", "Connection error.", 1, True),
    ("econnreset", "Error: read ECONNRESET", 1, True),
    ("stream-disconnected", "stream disconnected before completion", 1, True),
    ("rate-limit", "Rate limit exceeded, retry later", 1, True),
    ("status-429", "request failed with status code 429", 1, True),
    ("pr-number-429", "see PR #1429 for details", 1, False),
    ("line-number-503", "SyntaxError at app.py:503", 1, False),
    ("bad-flag", "error: unknown option '--frobnicate'", 2, False),
)


def _patch_spawn(monkeypatch: MonkeyPatch, module: Any, process: Any) -> None:
    monkeypatch.setattr(module, "spawn_agent_cli", lambda *_a, **_k: process)
    if hasattr(module, "_build_env"):
        monkeypatch.setattr(module, "_build_env", lambda _ctx: {})


@pytest.mark.parametrize("backend", _BACKENDS, ids=_BACKEND_IDS)
@pytest.mark.parametrize(
    ("stderr", "returncode", "advances"),
    [case[1:] for case in _FAILURES],
    ids=[case[0] for case in _FAILURES],
)
def test_cli_failure_failover_matrix(
    backend: _Backend,
    stderr: str,
    returncode: int,
    advances: bool,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    module = importlib.import_module(backend.module_name)
    ctx = make_agent_run_context(tmp_path, resolved_model="anthropic/claude-sonnet-5")
    _patch_spawn(
        monkeypatch,
        module,
        _FakeProcess(stdout=iter(()), stderr=f"{stderr}\n", returncode=returncode),
    )

    result = backend.invoke(module, ctx, tmp_path)

    assert result.success is False
    assert _may_advance_chain(result) is advances, (backend.name, stderr, result.metadata)


@pytest.mark.parametrize("backend", _BACKENDS, ids=_BACKEND_IDS)
def test_an_idle_stall_fails_over_on_every_backend(
    backend: _Backend, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    module = importlib.import_module(backend.module_name)
    ctx = make_agent_run_context(tmp_path, resolved_model="anthropic/claude-sonnet-5")
    ctx.idle_timeout_s = 0.05
    stop = threading.Event()

    def _kill(_pid: int | None, *, grace_s: float = 0.2) -> None:
        stop.set()

    monkeypatch.setattr("mergecraft.utils.process_group.kill_process_group", _kill)
    _patch_spawn(
        monkeypatch, module, _FakeProcess(stdout=_StallingStream(stop), stderr="", returncode=0)
    )

    result = backend.invoke(module, ctx, tmp_path)

    assert result.success is False
    assert result.metadata.get("idle_timeout") is True
    assert result.metadata.get("retryable") is True
    assert _may_advance_chain(result) is True


@pytest.mark.asyncio
async def test_a_driver_exception_becomes_a_failed_retryable_attempt(tmp_path: Path) -> None:
    async def _install(_token: str | None = None) -> str:
        return "fake"

    async def _run(_ctx: Any) -> AgentResult:
        raise httpx.ConnectError("serve process went away")

    crashing = agent(name="opencode", install=_install, run=_run)
    result = await crashing.run(make_agent_run_context(tmp_path, resolved_model=None))

    assert result.success is False
    assert result.metadata["crash"] is True
    assert "ConnectError" in (result.error or "")
    assert _may_advance_chain(result) is True


@pytest.mark.asyncio
async def test_a_crash_after_the_verdict_keeps_the_verdict(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A crash after an accepted submission still carries it to the chain classifier."""
    from mergecraft.agents import post_run

    monkeypatch.setattr(
        post_run, "_terminal_submission_fields", lambda _ctx: (True, "sub-accepted", {})
    )

    async def _install(_token: str | None = None) -> str:
        return "fake"

    async def _run(_ctx: Any) -> AgentResult:
        raise httpx.RemoteProtocolError("serve process went away after the verdict")

    crashing = agent(name="opencode", install=_install, run=_run)
    result = await crashing.run(make_agent_run_context(tmp_path, resolved_model=None))

    assert result.success is False
    assert result.terminal_submission_received is True
    assert result.terminal_submission_id == "sub-accepted"


@pytest.mark.parametrize(
    ("stderr", "advances"),
    [
        ('{"statusCode": 429, "message": "slow down"}', True),
        ('{"statusCode": 503, "message": "try later"}', True),
        ("HTTP/1.1 503 Service Unavailable", True),
        ("429 Too Many Requests", True),
        ('{"statusCode": 400, "message": "bad request"}', False),
    ],
    ids=["json-429", "json-503", "http-1.1-503", "429-too-many", "json-400"],
)
def test_status_code_outages_fail_over(stderr: str, advances: bool) -> None:
    from mergecraft.utils.provider_failure import is_retryable_cli_failure

    assert is_retryable_cli_failure(returncode=1, stderr=stderr) is advances


@pytest.mark.asyncio
async def test_a_configuration_error_still_ends_the_run(tmp_path: Path) -> None:
    from mergecraft.main import _ConfigurationError

    async def _install(_token: str | None = None) -> str:
        return "fake"

    async def _run(_ctx: Any) -> AgentResult:
        raise _ConfigurationError("privilege drop refused")

    refusing = agent(name="claude", install=_install, run=_run)
    with pytest.raises(_ConfigurationError):
        await refusing.run(make_agent_run_context(tmp_path, resolved_model=None))


@pytest.mark.asyncio
async def test_a_failed_initial_attempt_is_not_resumed(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """#1328 / AGT-F6 — the failed attempt reaches the chain with its own metadata."""
    from mergecraft.agents import post_run

    ctx = make_agent_run_context(tmp_path, resolved_model="openai/gpt-5.6-sol")

    async def _review_selected(*_args: Any, **_kwargs: Any) -> Any:
        from mergecraft.agents.shared import PostRunIssues

        return PostRunIssues(unsubmitted_review="Review")

    monkeypatch.setattr(post_run, "collect_post_run_issues", _review_selected)
    resumed: list[str] = []

    async def _resume(prompt: str) -> AgentResult:
        resumed.append(prompt)
        return AgentResult(success=False, error="resume died differently")

    initial = AgentResult(
        success=False,
        error="codex stalled",
        metadata={"idle_timeout": True, "retryable": True},
    )
    result = await run_post_run_retry_loop(ctx, initial=initial, resume=_resume)

    assert resumed == []
    assert result.error == "codex stalled"
    assert result.metadata == {"idle_timeout": True, "retryable": True}
