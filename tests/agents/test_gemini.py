"""Contract tests for the Gemini agent harness (issue #12 / D11)."""

from __future__ import annotations

import importlib
import json
import subprocess
from typing import TYPE_CHECKING

import pytest
from tests.agents.conftest import make_agent_run_context

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


def _load_gemini_module():
    try:
        return importlib.import_module("mergecraft.agents.gemini")
    except ImportError as exc:
        pytest.fail(f"mergecraft.agents.gemini not implemented: {exc}")


@pytest.mark.xfail(reason="green after W14: Gemini harness contract (#12)", strict=False)
def test_gemini_harness_invokes_cli_and_parses_agent_result(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Fake Gemini CLI on PATH + ``GEMINI_API_KEY`` → expected argv + ``AgentResult`` shape."""
    gemini_module = _load_gemini_module()
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("CI", "true")

    captured: list[list[str]] = []

    def _fake_run(
        cmd: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        captured.append(list(cmd))
        payload = {
            "result": "gemini review complete",
            "usage": {
                "input_tokens": 80,
                "output_tokens": 40,
            },
        }
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(gemini_module.subprocess, "run", _fake_run)

    ctx = make_agent_run_context(tmp_path, resolved_model="google/gemini-3.1-pro-preview")
    mcp_config = str(tmp_path / "mcp.json")
    (tmp_path / "mcp.json").write_text("{}", encoding="utf-8")

    result = gemini_module._run_gemini_once(
        cli="/usr/bin/gemini",
        prompt="review this diff",
        ctx=ctx,
        mcp_config=mcp_config,
    )

    assert captured, "expected gemini harness to invoke subprocess.run"
    cmd = captured[0]
    assert cmd[0] == "/usr/bin/gemini"
    assert "review this diff" in cmd

    assert result.success is True
    assert result.output is not None
    assert "gemini review complete" in result.output
    assert result.usage is not None
    assert result.usage.agent == "gemini"
    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0
