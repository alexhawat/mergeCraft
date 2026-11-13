"""Real CLI driver attempts share checkout and process supervision contracts."""

from __future__ import annotations

import importlib
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest
from tests.agents.conftest import make_agent_run_context

from mergecraft.utils.process_group import active_process_groups

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("backend", ["claude", "codex", "gemini", "opencode"], ids=str)
def test_driver_runs_in_review_checkout(
    backend: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module(f"mergecraft.agents.{backend}")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    ctx = make_agent_run_context(checkout, resolved_model=None)
    ctx.tmpdir = str(tmp_path / "scratch")
    if backend != "opencode":
        monkeypatch.setattr(module, "_build_env", lambda _ctx: {})
    original_popen = subprocess.Popen
    calls: list[dict[str, Any]] = []

    def spawn(_cmd: list[str], **kwargs: Any) -> subprocess.Popen[str]:
        calls.append(kwargs)
        return original_popen(
            [sys.executable, "-c", 'print(\'{"type":"result","result":"done"}\')'],
            **kwargs,
        )

    monkeypatch.setattr(subprocess, "Popen", spawn)
    if backend == "claude":
        module._run_claude_once(cli="claude", prompt="review", ctx=ctx, mcp_config="unused")
    elif backend == "opencode":
        module._run_opencode_cli_streaming(cmd=[backend], ctx=ctx, env={})
    else:
        getattr(module, f"_run_{backend}_streaming")(cmd=[backend], ctx=ctx, model=None)

    assert len(calls) == 1
    assert calls[0]["cwd"] == str(checkout)
    assert calls[0]["start_new_session"] is True


def test_opencode_version_probe_uses_filtered_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module("mergecraft.agents.opencode")
    monkeypatch.setattr(module, "_OPENCODE_MAJOR_CACHE", {})
    monkeypatch.setenv("GITHUB_TOKEN", "test-only-parent-token")
    monkeypatch.chdir(tmp_path)
    original_popen = subprocess.Popen
    calls: list[dict[str, Any]] = []

    def spawn(_cmd: list[str], **kwargs: Any) -> subprocess.Popen[str]:
        calls.append(kwargs)
        return original_popen([sys.executable, "-c", 'print("opencode v2.0.29")'], **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spawn)
    assert module._opencode_major_version("opencode") == 2
    assert "GITHUB_TOKEN" not in calls[0].get("env", {"GITHUB_TOKEN": "inherited"})
    assert calls[0]["start_new_session"] is True
    assert calls[0]["cwd"] == str(tmp_path)


def _invoke_driver(backend: str, ctx: Any) -> Any:
    module = importlib.import_module(f"mergecraft.agents.{backend}")
    if backend == "claude":
        return module._run_claude_once(cli="claude", prompt="review", ctx=ctx, mcp_config="unused")
    if backend == "opencode":
        return module._run_opencode_cli_streaming(cmd=[backend], ctx=ctx, env={})
    return getattr(module, f"_run_{backend}_streaming")(cmd=[backend], ctx=ctx, model=None)


_USAGE_EVENTS = {
    "claude": {
        "type": "result",
        "result": "done",
        "usage": {"input_tokens": 7, "output_tokens": 3},
    },
    "codex": {"type": "turn.completed", "usage": {"input_tokens": 7, "output_tokens": 3}},
    "gemini": {
        "type": "result",
        "response": "done",
        "usage": {"input_tokens": 7, "output_tokens": 3},
    },
    "opencode": {"type": "step_finish", "part": {"tokens": {"input": 7, "output": 3}, "cost": 0.1}},
}


@pytest.mark.parametrize("backend", list(_USAGE_EVENTS), ids=str)
@pytest.mark.parametrize("outcome", ["success", "failure", "timeout"], ids=str)
def test_driver_preserves_usage_across_attempt_outcomes(
    backend: str, outcome: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    module = importlib.import_module(f"mergecraft.agents.{backend}")
    if backend != "opencode":
        monkeypatch.setattr(module, "_build_env", lambda _ctx: {})
    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    monkeypatch.setenv("MERGECRAFT_AGENT_TIMEOUT", "1")
    script = (
        "import sys,time\n"
        f"print({json.dumps(_USAGE_EVENTS[backend])!r}, flush=True)\n"
        "sys.stderr.write('HTTP 503 Service Unavailable\\n')\n"
        "sys.stderr.flush()\n"
        + ("time.sleep(30)\n" if outcome == "timeout" else "")
        + f"sys.exit({1 if outcome == 'failure' else 0})\n"
    )
    original_popen = subprocess.Popen
    processes: list[subprocess.Popen[str]] = []

    def spawn(_cmd: list[str], **kwargs: Any) -> subprocess.Popen[str]:
        process = original_popen([sys.executable, "-c", script], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", spawn)
    try:
        result = _invoke_driver(backend, ctx)
        assert result.success is (outcome == "success")
        assert result.usage is not None
        assert result.usage.input_tokens == 7
        assert result.usage.output_tokens == 3
        if outcome != "success":
            assert result.metadata["retryable"] is True
        assert result.metadata.get("timeout", False) is (outcome == "timeout")
        assert len(processes) == 1
        assert processes[0].returncode is not None
        assert processes[0].pid not in active_process_groups()
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()


@pytest.mark.parametrize("backend", list(_USAGE_EVENTS), ids=str)
@pytest.mark.parametrize(
    "failure_boundary", ["consume_stream", "start_stderr_drain", "watchdog_for_process"]
)
def test_driver_reaps_child_when_supervision_raises(
    backend: str, failure_boundary: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.agents import cli_runner

    module = importlib.import_module(f"mergecraft.agents.{backend}")
    if backend != "opencode":
        monkeypatch.setattr(module, "_build_env", lambda _ctx: {})
    original_popen = subprocess.Popen
    processes: list[subprocess.Popen[str]] = []

    def spawn(_cmd: list[str], **kwargs: Any) -> subprocess.Popen[str]:
        process = original_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        processes.append(process)
        return process

    def fail_supervision(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("supervision failed")

    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(cli_runner, failure_boundary, fail_supervision)
    try:
        with pytest.raises(RuntimeError, match="supervision failed"):
            _invoke_driver(backend, make_agent_run_context(tmp_path, resolved_model=None))
        assert processes[0].returncode is not None
        assert processes[0].pid not in active_process_groups()
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()


def test_opencode_serve_preserves_identity_and_replaces_invalid_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module("mergecraft.agents.opencode")
    monkeypatch.setattr(
        "mergecraft.tracing.review_context.review_env_for_subprocess",
        lambda: {"MERGECRAFT_REVIEW_ID": "test-review-identity"},
    )
    original_popen = subprocess.Popen
    calls: list[dict[str, Any]] = []
    script = (
        "import sys,time\n"
        "sys.stdout.buffer.write(b'\\xff\\nlistening on http://127.0.0.1:12345\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n"
    )

    def spawn(_cmd: list[str], **kwargs: Any) -> subprocess.Popen[str]:
        calls.append(kwargs)
        return original_popen([sys.executable, "-c", script], **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spawn)
    handle = module._boot_opencode_server(cli="opencode", env={}, cwd=str(tmp_path))
    try:
        assert handle.base_url == "http://127.0.0.1:12345"
        assert calls[0]["env"]["MERGECRAFT_REVIEW_ID"] == "test-review-identity"
    finally:
        handle.close()
        for stream in (handle.proc.stdout, handle.proc.stderr):
            if stream is not None:
                stream.close()


def test_driver_validates_timeout_before_spawning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic import ValidationError

    module = importlib.import_module("mergecraft.agents.gemini")
    monkeypatch.setattr(module, "_build_env", lambda _ctx: {})
    monkeypatch.setenv("MERGECRAFT_AGENT_TIMEOUT", "not-a-number")
    original_popen = subprocess.Popen
    processes: list[subprocess.Popen[str]] = []

    def spawn(_cmd: list[str], **kwargs: Any) -> subprocess.Popen[str]:
        process = original_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", spawn)
    try:
        with pytest.raises(ValidationError):
            _invoke_driver("gemini", make_agent_run_context(tmp_path, resolved_model=None))
        assert not processes, "invalid timeout must fail before a provider process exists"
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
