"""A second attempt keeps the refreshed Codex login, and runs do not share state (#1327)."""

from __future__ import annotations

import asyncio
import contextvars
import json
from typing import TYPE_CHECKING, Any

import pytest
from tests.agents.conftest import make_agent_run_context

from mergecraft.agents import claude as claude_module
from mergecraft.agents import codex as codex_module
from mergecraft.agents import codex_broker
from mergecraft.security.broker import CodexBrokerPosture

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_ORIGINAL = json.dumps(
    {"tokens": {"refresh_token": "rt-old-aaaa", "access_token": "at-0", "account_id": "acct-1"}}
)
_REFRESHED = json.dumps(
    {"tokens": {"refresh_token": "rt-new-bbbb", "access_token": "at-1", "account_id": "acct-1"}}
)
_OTHER_SECRET = json.dumps(
    {"tokens": {"refresh_token": "rt-zzz", "access_token": "at-9", "account_id": "acct-2"}}
)


def test_a_second_attempt_keeps_the_refreshed_login(tmp_path: Path) -> None:
    ctx = make_agent_run_context(tmp_path, resolved_model="openai/gpt-codex")
    home = tmp_path / "home" / ".codex"
    secret = {codex_module.CODEX_AUTH_ENV: _ORIGINAL}

    codex_module._setup_codex_auth(ctx, codex_home=home, credential_env=secret)
    assert (home / "auth.json").read_text(encoding="utf-8") == _ORIGINAL
    # Codex refreshed the login during attempt 1 and rewrote auth.json.
    (home / "auth.json").write_text(_REFRESHED, encoding="utf-8")

    # Attempt 2 (a post-run resume or a same-harness chain rung) re-runs setup.
    codex_module._setup_codex_auth(ctx, codex_home=home, credential_env=secret)

    assert (home / "auth.json").read_text(encoding="utf-8") == _REFRESHED
    export = tmp_path / "out" / "auth.json"
    assert codex_module.export_refreshed_codex_auth(
        codex_home=home, original=_ORIGINAL, export_path=export
    )
    assert export.read_text(encoding="utf-8") == _REFRESHED


def test_a_different_secret_still_replaces_the_file(tmp_path: Path) -> None:
    ctx = make_agent_run_context(tmp_path, resolved_model="openai/gpt-codex")
    home = tmp_path / "home2" / ".codex"
    codex_module._setup_codex_auth(
        ctx, codex_home=home, credential_env={codex_module.CODEX_AUTH_ENV: _ORIGINAL}
    )
    codex_module._setup_codex_auth(
        ctx, codex_home=home, credential_env={codex_module.CODEX_AUTH_ENV: _OTHER_SECRET}
    )
    assert (home / "auth.json").read_text(encoding="utf-8") == _OTHER_SECRET


def test_a_stale_file_this_process_did_not_seed_is_overwritten(tmp_path: Path) -> None:
    ctx = make_agent_run_context(tmp_path, resolved_model="openai/gpt-codex")
    home = tmp_path / "home3" / ".codex"
    home.mkdir(parents=True)
    (home / "auth.json").write_text(_REFRESHED, encoding="utf-8")
    codex_module._setup_codex_auth(
        ctx, codex_home=home, credential_env={codex_module.CODEX_AUTH_ENV: _ORIGINAL}
    )
    assert (home / "auth.json").read_text(encoding="utf-8") == _ORIGINAL


def _session(stopped: list[str], name: str) -> codex_broker.CodexBrokerSession:
    class _Cm:
        def __exit__(self, *_exc: object) -> None:
            stopped.append(name)

    posture = CodexBrokerPosture(active=True, auth_mode="api_key", reason="test")
    return codex_broker.CodexBrokerSession(posture=posture, handle=None, _broker_cm=_Cm())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_concurrent_runs_keep_their_own_broker_session() -> None:
    """Run B starting its broker no longer stops run A's broker mid-request."""
    stopped: list[str] = []
    a_ready = asyncio.Event()
    b_done = asyncio.Event()
    seen: dict[str, Any] = {}

    async def _run_a() -> None:
        session_a = _session(stopped, "a")
        codex_broker.set_broker_session(session_a)
        a_ready.set()
        await b_done.wait()
        seen["a"] = codex_broker.current_broker_session() is session_a

    async def _run_b() -> None:
        await a_ready.wait()
        session_b = _session(stopped, "b")
        codex_broker.set_broker_session(session_b)
        seen["b"] = codex_broker.current_broker_session() is session_b
        b_done.set()

    await asyncio.gather(
        asyncio.create_task(_run_a(), context=contextvars.copy_context()),
        asyncio.create_task(_run_b(), context=contextvars.copy_context()),
    )

    assert seen == {"a": True, "b": True}
    assert stopped == []


def test_claude_resume_names_the_recorded_session(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """A Claude resume targets this run's own session, not ``--continue``."""
    import io

    captured: list[list[str]] = []
    stdout = '{"type": "system", "subtype": "init", "session_id": "sess-a-1"}\n'

    class _Proc:
        def __init__(self) -> None:
            self.stdout = io.StringIO(stdout)
            self.stderr = io.StringIO("")
            self.pid = 987655

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def poll(self) -> int:
            return 0

    def _spawn(cmd: list[str], **_kwargs: object) -> _Proc:
        captured.append(list(cmd))
        return _Proc()

    monkeypatch.setattr(claude_module, "spawn_agent_cli", _spawn)
    monkeypatch.setattr(claude_module, "_build_env", lambda _ctx: {})
    ctx = make_agent_run_context(tmp_path, resolved_model="anthropic/claude-opus")
    session: dict[str, str] = {}
    for continue_session in (False, True):
        claude_module._run_claude_once(
            cli="/usr/bin/claude",
            prompt="go",
            ctx=ctx,
            mcp_config=str(tmp_path / "mcp.json"),
            continue_session=continue_session,
            session=session,
        )

    assert session == {"session_id": "sess-a-1"}
    resumed = captured[1]
    assert resumed[resumed.index("--resume") + 1] == "sess-a-1"
    assert "--continue" not in resumed
