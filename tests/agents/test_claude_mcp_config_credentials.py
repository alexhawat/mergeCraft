"""The Claude run's MCP config names the bearer's env var instead of holding it.

``.claude/mcp.json`` writes ``Authorization: Bearer ${MERGECRAFT_MCP_TOKEN}``;
Claude Code expands ``${VAR}`` in ``--mcp-config`` server headers at load
(pinned against the real CLI in ``test_header_reference_expands_in_the_real_cli``).
The value rides only the child environment, and the config directory is denied
to Claude's read and edit tools.
"""

from __future__ import annotations

import contextlib
import http.server
import importlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from mergecraft.agents import claude
from mergecraft.agents.shared import AgentRunContext, ResolvedInstructions
from mergecraft.agents.verifier import VERIFIER_AGENT_NAME
from mergecraft.config.env import McpEnv
from mergecraft.mcp.context import PayloadEvent, ResolvedPayload
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.types import MERGECRAFT_MCP_NAME, MERGECRAFT_VERIFIER_MCP_NAME

_MCP_TOKEN = "mcp-token-placeholder-4d2e"
_TOKEN_ENV = str(McpEnv.model_fields["mcp_token"].validation_alias)


def _ctx(tmp_path: Path, *, token: str = _MCP_TOKEN) -> AgentRunContext:
    return AgentRunContext(
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        mcp_server_url="http://127.0.0.1:0/mcp",
        tmpdir=str(tmp_path),
        subagent_denied_tools=(),
        instructions=ResolvedInstructions(user="review this diff"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_auth_token=token,
        resolved_model="anthropic/claude-sonnet-5",
    )


def test_mcp_config_names_the_bearer_env_var(tmp_path: Path) -> None:
    path = Path(claude.write_mcp_config(_ctx(tmp_path)))

    raw = path.read_text(encoding="utf-8")
    assert _MCP_TOKEN not in raw
    servers = json.loads(raw)["mcpServers"]
    for name, agent_id in (
        (MERGECRAFT_MCP_NAME, "claude"),
        (MERGECRAFT_VERIFIER_MCP_NAME, VERIFIER_AGENT_NAME),
    ):
        assert servers[name]["headers"] == {
            "Authorization": f"Bearer ${{{_TOKEN_ENV}}}",
            "X-MergeCraft-Agent-Id": agent_id,
        }


def test_mcp_config_without_a_token_has_no_authorization(tmp_path: Path) -> None:
    path = Path(claude.write_mcp_config(_ctx(tmp_path, token="")))

    servers = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
    assert "Authorization" not in servers[MERGECRAFT_MCP_NAME].get("headers", {})


class _EmptyProcess:
    def __init__(self) -> None:
        self.stdout = iter(())
        self.stderr = type("_R", (), {"read": staticmethod(lambda: "")})()
        self.pid = 4242

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def poll(self) -> int:
        return 0


def _launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[list[str], dict[str, str]]:
    """Run the driver's real spawn path with the process stubbed; return argv and env."""
    module = importlib.import_module("mergecraft.agents.claude")
    seen: list[tuple[list[str], dict[str, str]]] = []

    def _spawn(cmd: list[str], *, env: dict[str, str], **_k: Any) -> _EmptyProcess:
        seen.append((list(cmd), dict(env)))
        return _EmptyProcess()

    monkeypatch.setattr(module, "spawn_agent_cli", _spawn)
    monkeypatch.setattr(module, "track_process_group", lambda *_a, **_k: contextlib.nullcontext())
    monkeypatch.setattr(module, "wait_or_kill_process_group", lambda proc, timeout: proc.wait())

    ctx = _ctx(tmp_path)
    claude._run_claude_once(
        cli="/usr/bin/claude",
        prompt="review this diff",
        ctx=ctx,
        mcp_config=claude.write_mcp_config(ctx),
    )
    assert seen, "driver never spawned the CLI"
    return seen[0]


def test_child_env_carries_the_bearer_the_config_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_TOKEN_ENV, raising=False)

    _argv, env = _launch(tmp_path, monkeypatch)

    assert env[_TOKEN_ENV] == _MCP_TOKEN


def test_config_directory_is_denied_to_read_and_edit_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv, _env = _launch(tmp_path, monkeypatch)

    config_path = Path(argv[argv.index("--mcp-config") + 1])
    config_dir = config_path.parent.as_posix().lstrip("/")
    rules = argv[argv.index("--disallowedTools") + 1].split(",")
    for verb in ("Read", "Edit"):
        assert f"{verb}(//{config_dir})" in rules
        assert f"{verb}(//{config_dir}/**)" in rules


# ── the real CLI expands the reference ───────────────────────────────────────


class _HeaderLog(http.server.BaseHTTPRequestHandler):
    seen: list[tuple[str, str | None]] = []  # noqa: RUF012 — per-test reset below

    def _record(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        if length:
            self.rfile.read(length)
        # Only the MCP route's header is kept; the model route gets an error.
        auth = self.headers.get("Authorization") if self.path.startswith("/mcp") else None
        self.seen.append((self.path, auth))
        self.send_response(401 if self.path.startswith("/mcp") else 500)
        self.end_headers()

    do_GET = do_POST = do_DELETE = _record

    def log_message(self, *_args: object) -> None:
        return


@pytest.mark.integration
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX CLI")
def test_header_reference_expands_in_the_real_cli(tmp_path: Path) -> None:
    """Claude Code expands ``${VAR}`` in an ``--mcp-config`` server header.

    The model endpoint points at the same local server, so no request leaves
    the machine.
    """
    cli = shutil.which("claude")
    if cli is None:
        pytest.skip("claude CLI not installed")
    _HeaderLog.seen = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HeaderLog)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    ctx = AgentRunContext(
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        mcp_server_url=f"{base}/mcp",
        tmpdir=str(run_dir),
        subagent_denied_tools=(),
        instructions=ResolvedInstructions(user="x"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_auth_token=_MCP_TOKEN,
    )
    config = claude.write_mcp_config(ctx)
    (tmp_path / "home").mkdir()
    (tmp_path / "cfg").mkdir()
    env = {
        "HOME": str(tmp_path / "home"),
        "PATH": os.environ.get("PATH", ""),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "cfg"),
        "ANTHROPIC_BASE_URL": base,
        "ANTHROPIC_API_KEY": "placeholder-not-a-key",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        _TOKEN_ENV: _MCP_TOKEN,
    }
    proc = subprocess.Popen(
        # ``--mcp-config`` takes several values, so the prompt goes before it.
        [cli, "--print", "x", "--strict-mcp-config", "--mcp-config", config],
        cwd=run_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline and proc.poll() is None:
            if any(path.startswith("/mcp") for path, _ in _HeaderLog.seen):
                break
            time.sleep(0.2)
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)
        server.shutdown()

    mcp_auth = {auth for path, auth in _HeaderLog.seen if path.startswith("/mcp")}
    assert mcp_auth == {f"Bearer {_MCP_TOKEN}"}
