"""Contract tests for the Codex/OpenAI agent harness (issue #10/#11 / D10)."""

from __future__ import annotations

import importlib
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from tests.agents.conftest import make_agent_run_context

if TYPE_CHECKING:
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


def test_write_mcp_config_uses_permission_profiles_for_read_only_mcp(tmp_path: Path) -> None:
    """shell=disabled + MCP → permission profiles (legacy read-only has no network knob)."""
    codex_module = _load_codex_module()
    ctx = make_agent_run_context(tmp_path, resolved_model="openai/gpt-5.3-codex")
    ctx.payload.shell = "disabled"

    config_path = Path(codex_module.write_mcp_config(ctx))
    text = config_path.read_text(encoding="utf-8")

    assert "sandbox_mode" not in text
    assert "[permissions.mergecraft-review]" in text
    assert 'extends = ":read-only"' in text
    assert "[permissions.mergecraft-review.network]" in text
    assert "enabled = true" in text
    assert "allow_local_binding = true" in text
    assert "[sandbox_read_only]" not in text
    assert "[mcp_servers.mergecraft]" in text

    instructions = (tmp_path / ".codex" / "mergecraft-instructions.md").read_text(encoding="utf-8")
    assert "Do **not** install, request, enable, or wait for any GitHub plugin" in instructions
    assert "mergecraft_checkout_pr" in instructions


def test_write_mcp_config_omits_github_plugin_preamble_without_mcp_url(tmp_path: Path) -> None:
    codex_module = _load_codex_module()
    ctx = make_agent_run_context(tmp_path, resolved_model="openai/gpt-5.3-codex")
    ctx.mcp_server_url = ""
    ctx.payload.shell = "disabled"

    codex_module.write_mcp_config(ctx)
    instructions = (tmp_path / ".codex" / "mergecraft-instructions.md").read_text(encoding="utf-8")
    assert "GitHub plugin" not in instructions
    assert "mergecraft_checkout_pr" not in instructions


def test_write_mcp_config_omits_permission_profiles_without_mcp_url(tmp_path: Path) -> None:
    codex_module = _load_codex_module()
    ctx = make_agent_run_context(tmp_path, resolved_model="openai/gpt-5.3-codex")
    ctx.mcp_server_url = ""
    ctx.payload.shell = "disabled"

    config_path = Path(codex_module.write_mcp_config(ctx))
    text = config_path.read_text(encoding="utf-8")

    assert 'sandbox_mode = "read-only"' in text
    assert "default_permissions" not in text
    assert "network_access" not in text
    assert "[mcp_servers.mergecraft]" not in text


def test_write_mcp_config_auto_approves_mergecraft_tools(tmp_path: Path) -> None:
    """Read-only reviews must not need an approver for their own MCP tools.

    Codex only auto-approves an MCP tool call when the permission profile grants
    full disk write access, which the review profile deliberately does not. With
    ``approval_policy = "never"`` and nobody to answer the elicitation, every
    call resolves to "user cancelled MCP tool call" unless the server declares
    its tools pre-approved.
    """
    codex_module = _load_codex_module()
    ctx = make_agent_run_context(tmp_path, resolved_model="openai/gpt-5.3-codex")
    ctx.payload.shell = "disabled"

    config_path = Path(codex_module.write_mcp_config(ctx))
    text = config_path.read_text(encoding="utf-8")

    server_block = text.split("[mcp_servers.mergecraft]", 1)[1]
    assert 'default_tools_approval_mode = "approve"' in server_block


def test_write_mcp_config_keeps_mutating_tools_for_the_main_session(
    tmp_path: Path,
) -> None:
    """Subagent deny list must not hide checkout/review tools from Codex itself.

    ``subagent_denied_tools`` is every mutates=True MCP tool. Putting that list
    into Codex's ``disabled_tools`` made the primary reviewer unable to call
    ``checkout_pr`` or ``create_pull_request_review``, so every review posted
    ``mergecraft-approval=neutral`` even when Codex wanted to approve.
    """
    codex_module = _load_codex_module()
    ctx = make_agent_run_context(tmp_path, resolved_model="openai/gpt-5.3-codex")
    ctx.payload.shell = "disabled"
    ctx.subagent_denied_tools = ("checkout_pr", "create_pull_request_review", "push_branch")

    config_path = Path(codex_module.write_mcp_config(ctx))
    text = config_path.read_text(encoding="utf-8")

    server_block = text.split("[mcp_servers.mergecraft]", 1)[1]
    assert "disabled_tools" not in server_block
    assert "checkout_pr" not in server_block
    assert "create_pull_request_review" not in server_block


def test_write_mcp_config_enables_network_in_workspace_write_sandbox(tmp_path: Path) -> None:
    codex_module = _load_codex_module()
    ctx = make_agent_run_context(tmp_path, resolved_model="openai/gpt-5.3-codex")
    ctx.payload.shell = "enabled"

    config_path = Path(codex_module.write_mcp_config(ctx))
    text = config_path.read_text(encoding="utf-8")

    assert 'sandbox_mode = "workspace-write"' in text
    assert "[sandbox_workspace_write]" in text
    assert "network_access = true" in text
    assert "default_permissions" not in text


def test_run_codex_once_omits_sandbox_flag_for_permission_profiles(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    codex_module = _load_codex_module()
    monkeypatch.setenv("CI", "true")
    captured: list[list[str]] = []

    def _fake_run(
        cmd: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        captured.append(list(cmd))
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout='{"result":"ok"}',
            stderr="",
        )

    monkeypatch.setattr(codex_module.subprocess, "run", _fake_run)
    ctx = make_agent_run_context(tmp_path, resolved_model="openai/gpt-5.3-codex")
    ctx.payload.shell = "disabled"
    codex_module.write_mcp_config(ctx)

    codex_module._run_codex_once(
        cli="/usr/bin/codex",
        prompt="review",
        ctx=ctx,
        mcp_config=str(tmp_path / "unused"),
    )

    cmd = captured[0]
    assert "--sandbox" not in cmd
