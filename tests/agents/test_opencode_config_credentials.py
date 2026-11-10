"""The OpenCode run config names credential env vars instead of carrying values.

The provider ``apiKey`` and the MCP ``Authorization`` header are written as
``{env:NAME}`` references, which OpenCode substitutes at load (pinned against the
real 2.x CLI in ``test_env_references_resolve_in_the_real_cli``). The values ride
only the child environment. The config file is written ``0600`` into a private
run-temp child the reviewer's permissions deny, not into the evidence directory.
"""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import http.server
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from mergecraft.agents import opencode as oc
from mergecraft.agents.shared import AgentResult, AgentRunContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.types import MERGECRAFT_MCP_NAME

_PROVIDER_KEY = "provider-key-placeholder-7f3a"
_MCP_TOKEN = "mcp-token-placeholder-91bc"
_KEY_ENV = "MERGECRAFT_CUSTOM_PROVIDER_API_KEY_1"
_MODEL = "provider_1/some-model"


@pytest.fixture(autouse=True)
def _provider_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in list(os.environ):
        if name.startswith(("MERGECRAFT_CUSTOM_PROVIDER_", "LLM_PROVIDER_")):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_1", "https://gw.example.test/v1")
    monkeypatch.setenv(_KEY_ENV, _PROVIDER_KEY)
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    monkeypatch.setenv("MERGECRAFT_EVIDENCE_DIR", str(tmp_path / "evidence"))


def _ctx(tmp_path: Path) -> AgentRunContext:
    """A run whose temp dir sits outside the checkout, as in production."""
    from mergecraft.utils.git_setup import register_run_owned_directory

    run_dir = tmp_path / "run"
    repo = tmp_path / "repo"
    run_dir.mkdir()
    repo.mkdir()
    register_run_owned_directory(str(run_dir))
    return AgentRunContext(
        payload={"shell": "restricted", "push": "restricted"},
        mcp_server_url="http://127.0.0.1:0/mcp",
        tmpdir=str(run_dir),
        subagent_denied_tools=(),
        instructions="review",
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(repo)),
        mcp_auth_token=_MCP_TOKEN,
        resolved_model=_MODEL,
    )


def _no_secret(text: str) -> None:
    assert _PROVIDER_KEY not in text
    assert _MCP_TOKEN not in text


def test_config_references_credential_env_names(tmp_path: Path) -> None:
    raw = oc.build_security_config(_ctx(tmp_path), _MODEL)

    _no_secret(raw)
    config = json.loads(raw)
    assert config["provider"]["provider_1"]["options"]["apiKey"] == f"{{env:{_KEY_ENV}}}"
    assert config["mcp"][MERGECRAFT_MCP_NAME]["headers"] == {
        "Authorization": "Bearer {env:MERGECRAFT_MCP_TOKEN}"
    }


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the CLI so ``_run`` records the env it would launch OpenCode with."""
    monkeypatch.setattr(oc, "_OPENCODE_MAJOR_CACHE", {})
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/opencode")
    monkeypatch.setattr(oc, "_opencode_major_version", lambda _cli: 2)
    seen: dict[str, Any] = {}

    async def _v2(*, cli: str, ctx: Any, env: dict[str, str], model: str | None) -> AgentResult:
        seen["env"] = env
        return AgentResult(success=True, output="ok")

    monkeypatch.setattr(oc, "_run_v2", _v2)
    return seen


async def test_run_writes_a_private_config_without_secret_values(
    tmp_path: Path, launched: dict[str, Any]
) -> None:
    ctx = _ctx(tmp_path)

    result = await oc._run(ctx)

    assert result.success is True
    env = launched["env"]
    _no_secret(env["OPENCODE_CONFIG_CONTENT"])
    # The values the references name reach OpenCode through its environment only.
    assert env[_KEY_ENV] == _PROVIDER_KEY
    assert env["MERGECRAFT_MCP_TOKEN"] == _MCP_TOKEN

    await asyncio.to_thread(_assert_private_config_on_disk, ctx, env)


def _assert_private_config_on_disk(ctx: AgentRunContext, env: dict[str, str]) -> None:
    config_path = Path(env["OPENCODE_CONFIG"])
    on_disk = config_path.read_text(encoding="utf-8")
    _no_secret(on_disk)
    assert on_disk == env["OPENCODE_CONFIG_CONTENT"]
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
    assert config_path.parent == Path(ctx.tmpdir) / "opencode-run-config"
    # Nothing under the evidence directory carries a credential.
    evidence = oc._evidence_dir(ctx)
    assert not evidence.is_relative_to(config_path.parent)
    for item in evidence.rglob("*") if evidence.exists() else ():
        if item.is_file():
            _no_secret(item.read_text(encoding="utf-8", errors="replace"))


async def test_config_file_sits_where_review_permissions_deny(
    tmp_path: Path, launched: dict[str, Any]
) -> None:
    ctx = _ctx(tmp_path)

    await oc._run(ctx)

    resolved = await asyncio.to_thread(Path(launched["env"]["OPENCODE_CONFIG"]).resolve)
    config_path = resolved.as_posix()
    permission = json.loads(launched["env"]["OPENCODE_CONFIG_CONTENT"])["permission"]
    verdict = None
    for pattern, action in permission["external_directory"].items():
        if fnmatch.fnmatchcase(config_path, pattern.replace("**", "*")):
            verdict = action
    assert verdict == "deny"
    for pattern, action in permission["read"].items():
        if action == "allow":
            assert not fnmatch.fnmatchcase(config_path, pattern.replace("**", "*"))


# ── the real CLI substitutes the references ──────────────────────────────────


class _HeaderLog(http.server.BaseHTTPRequestHandler):
    seen: list[tuple[str, str | None]] = []  # noqa: RUF012 — per-test reset below

    def _record(self) -> None:
        self.seen.append((self.path, self.headers.get("Authorization")))
        self.send_response(500)
        self.end_headers()

    do_GET = do_POST = do_DELETE = _record

    def log_message(self, *_args: object) -> None:
        return


def _opencode_2x() -> str | None:
    cli = shutil.which("opencode")
    if cli is None:
        return None
    major = oc._opencode_major_version(cli)
    return cli if major is not None and major >= 2 else None


@pytest.mark.integration
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX CLI")
def test_env_references_resolve_in_the_real_cli(tmp_path: Path) -> None:
    """OpenCode 2.x expands ``{env:NAME}`` in the provider key and the MCP header."""
    cli = _opencode_2x()
    if cli is None:
        pytest.skip("opencode 2.x CLI not installed")
    _HeaderLog.seen = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HeaderLog)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    config = {
        "provider": {
            "gw": {
                "npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": f"{base}/v1", "apiKey": "{env:PROBE_PROVIDER_KEY}"},
                "models": {"m": {}},
            }
        },
        "mcp": {
            "mergecraft": {
                "type": "remote",
                "url": f"{base}/mcp",
                "headers": {"Authorization": "Bearer {env:PROBE_MCP_TOKEN}"},
            }
        },
    }
    (tmp_path / "home").mkdir()
    (tmp_path / "cfg").mkdir()
    (tmp_path / "repo").mkdir()
    env = {
        "HOME": str(tmp_path / "home"),
        "PATH": os.environ.get("PATH", ""),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "XDG_DATA_HOME": str(tmp_path / "home" / "data"),
        "OPENCODE_CONFIG_DIR": str(tmp_path / "cfg"),
        "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
        "OPENCODE_CONFIG_CONTENT": json.dumps(config),
        "PROBE_PROVIDER_KEY": _PROVIDER_KEY,
        "PROBE_MCP_TOKEN": _MCP_TOKEN,
    }
    routes = {"/mcp", "/v1/chat/completions"}
    proc = subprocess.Popen(
        [cli, "run", "--standalone", "-m", "gw/m", "x"],
        cwd=tmp_path / "repo",
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        # Stop as soon as both endpoints were called: the CLI retries the failing
        # gateway for a long time otherwise.
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline and proc.poll() is None:
            if routes <= {path.split("?")[0] for path, _ in _HeaderLog.seen}:
                break
            time.sleep(0.2)
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)
        server.shutdown()

    auth_by_route = {path.split("?")[0]: auth for path, auth in _HeaderLog.seen}
    assert auth_by_route.get("/mcp") == f"Bearer {_MCP_TOKEN}"
    assert auth_by_route.get("/v1/chat/completions") == f"Bearer {_PROVIDER_KEY}"
