"""Contract tests for the Gemini agent harness (issue #12 / D11)."""

from __future__ import annotations

import importlib
import json
import time
from typing import TYPE_CHECKING, Any

import pytest
from tests.agents.conftest import make_agent_run_context

from mergecraft.agents import cli_runner

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


def _load_gemini_module():
    try:
        return importlib.import_module("mergecraft.agents.gemini")
    except ImportError as exc:
        pytest.fail(f"mergecraft.agents.gemini not implemented: {exc}")


class _FakeGeminiProcess:
    """Minimal ``subprocess.Popen`` look-alike for the W6 gemini read loop."""

    def __init__(self, *, stdout: str, stderr: str, returncode: int) -> None:
        self._stdout_text = stdout
        self._stderr_text = stderr
        self.stdout: list[str] = stdout.splitlines(keepends=True) or [""]
        self.stderr: Any = self
        self.stdin: Any = None
        self.returncode = returncode

    def read(self) -> str:
        return self._stderr_text

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self.returncode

    def __iter__(self) -> Any:
        return iter(self.stdout)


def test_gemini_harness_invokes_cli_and_parses_agent_result(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Fake Gemini CLI on PATH + ``GEMINI_API_KEY`` → expected argv + ``AgentResult`` shape."""
    gemini_module = _load_gemini_module()
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("CI", "true")

    captured: list[list[str]] = []
    payload = {
        "result": "gemini review complete",
        "usage": {
            "input_tokens": 80,
            "output_tokens": 40,
        },
    }

    fed: list[str] = []

    class _Stdin:
        def write(self, text: str) -> None:
            fed.append(text)

        def close(self) -> None: ...

    def _fake_popen(cmd: list[str], **kwargs: object) -> object:
        captured.append(list(cmd))
        proc = _FakeGeminiProcess(stdout=json.dumps(payload), stderr="", returncode=0)
        proc.stdin = _Stdin()
        return proc

    monkeypatch.setattr(cli_runner.subprocess, "Popen", _fake_popen)

    ctx = make_agent_run_context(tmp_path, resolved_model="google/gemini-3.1-pro-preview")
    mcp_config = str(tmp_path / "mcp.json")
    (tmp_path / "mcp.json").write_text("{}", encoding="utf-8")

    result = gemini_module._run_gemini_once(
        cli="/usr/bin/gemini",
        prompt="review this diff",
        ctx=ctx,
        mcp_config=mcp_config,
    )

    assert captured, "expected gemini harness to invoke subprocess.Popen"
    cmd = captured[0]
    assert cmd[0] == "/usr/bin/gemini"
    # The prompt rides on stdin; ``-p`` only carries the trailer (#1329).
    assert cmd[cmd.index("-p") + 1] == gemini_module.GEMINI_STDIN_PROMPT_TRAILER
    for _ in range(50):
        if fed:
            break
        time.sleep(0.02)
    prompt_arg = "".join(fed)
    assert "review this diff" in prompt_arg
    assert "mergecraft-reviewer" in prompt_arg

    assert result.success is True
    assert result.output is not None
    assert "gemini review complete" in result.output
    assert result.usage is not None
    assert result.usage.agent == "gemini"
    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0
