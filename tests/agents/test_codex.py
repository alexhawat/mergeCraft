"""Contract tests for the Codex/OpenAI agent harness (issue #10/#11 / D10)."""

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


def _load_codex_module():
    try:
        return importlib.import_module("mergecraft.agents.codex")
    except ImportError as exc:
        pytest.fail(f"mergecraft.agents.codex not implemented: {exc}")


def test_codex_harness_invokes_cli_and_parses_agent_result(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Fake ``codex`` on PATH + ``CODEX_AUTH_JSON`` → expected argv + ``AgentResult`` shape."""
    codex_module = _load_codex_module()
    monkeypatch.setenv("CODEX_AUTH_JSON", '{"access_token":"test-token"}')
    monkeypatch.setenv("CI", "true")

    captured: list[list[str]] = []

    def _fake_run(
        cmd: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        captured.append(list(cmd))
        payload = {
            "result": "review complete",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
            },
            "total_cost_usd": 0.01,
        }
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(codex_module.subprocess, "run", _fake_run)

    ctx = make_agent_run_context(tmp_path, resolved_model="openai/gpt-5.3-codex")
    mcp_config = str(tmp_path / "mcp.json")
    (tmp_path / "mcp.json").write_text("{}", encoding="utf-8")

    result = codex_module._run_codex_once(
        cli="/usr/bin/codex",
        prompt="review this diff",
        ctx=ctx,
        mcp_config=mcp_config,
    )

    assert captured, "expected codex harness to invoke subprocess.run"
    cmd = captured[0]
    assert cmd[0] == "/usr/bin/codex"
    assert "review this diff" in cmd
    assert any("--model" in arg or "gpt-5.3-codex" in arg for arg in cmd)

    assert result.success is True
    assert result.output is not None
    assert "review complete" in result.output
    assert result.usage is not None
    assert result.usage.agent == "codex"
    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0
