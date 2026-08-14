"""Real subprocess-launch sites redirect HOME under the privilege drop (live-bug fix).

``setpriv --reuid/--regid`` (``mergecraft.utils.privilege.wrap_agent_command``)
drops the agent subprocess's uid/gid but does not reset ``$HOME`` the way
``su -``/``sudo -H`` would. The container sets ``HOME=/github/home`` (owned by
the runner's original uid), so the dropped-to agent user cannot write
dotfiles/config under it — this is the exact failure behind the observed
``opencode serve exited early: EACCES: permission denied, mkdir
'/github/home/.local'`` and the equivalent Codex failure.

These tests drive the three real subprocess-launch call sites — the shared
``spawn_agent_cli`` (covers Codex/Gemini/Claude's primary streaming path/most
of OpenCode), OpenCode's ``_boot_opencode_server`` bypass, and Claude's legacy
``subprocess.run`` bypass — with root simulated via monkeypatched
``os.getuid``/``pwd.getpwnam``, and assert the env actually handed to
``Popen``/``subprocess.run`` has ``HOME``/``USER``/``LOGNAME`` redirected to
the resolved agent user, while argv is still ``setpriv``-wrapped exactly as
before.

A second, related but distinct bug: Codex does not use ``$HOME`` at all — it
uses its own ``$CODEX_HOME`` (``codex.py::_codex_home``), a directory that
``write_mcp_config()``/``_setup_codex_auth()`` create and write into (as
root) *before* the privilege-dropped subprocess starts. The ``HOME`` redirect
above does not touch this separate directory, so it stayed root-owned and
Codex's own PATH-alias bootstrap failed closed with the same class of
``Permission denied (os error 13)`` — confirmed live on PR #175/#189 even
after the ``HOME`` fix landed. ``codex.py::_build_env`` now chowns
``$CODEX_HOME`` via ``prepare_workspace_for_agent`` as its last step, mirroring
the checkout-workspace chown that already existed for W3.4.
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from tests.agents.conftest import make_agent_run_context

from mergecraft.agents.shared import spawn_agent_cli
from mergecraft.utils import privilege as privilege_module

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

# ``mergecraft.agents.__init__`` reassigns the ``claude``/``opencode`` package
# attributes to the built ``AgentImpl`` instances (``from .claude import
# claude``), which shadows the submodules for ``import ... as`` attribute
# resolution. Go through ``sys.modules`` via ``importlib`` to get the actual
# submodules, matching how ``tests/agents/test_codex.py`` resolves
# ``mergecraft.agents.codex``.
claude_module = importlib.import_module("mergecraft.agents.claude")
opencode_module = importlib.import_module("mergecraft.agents.opencode")
codex_module = importlib.import_module("mergecraft.agents.codex")
gemini_module = importlib.import_module("mergecraft.agents.gemini")


class _FakePw:
    pw_name = "mergecraft"
    pw_uid = 1001
    pw_gid = 1001
    pw_dir = "/home/mergecraft"


def _simulate_root_privilege_drop(monkeypatch: MonkeyPatch) -> None:
    """Make every branch in ``wrap_agent_command``/``agent_subprocess_env`` see
    the action-image root path: ``setpriv`` present, ``mergecraft`` resolves,
    and the current (inherited, GitHub-Actions-container-style) ``HOME`` is
    NOT owned by the resolved agent uid — the exact live-bug scenario."""
    monkeypatch.setattr(privilege_module.os, "getuid", lambda: 0)
    monkeypatch.setattr(
        privilege_module.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name == "setpriv" else None,
    )
    monkeypatch.setattr(privilege_module.os, "stat", lambda _path: MagicMock(st_uid=0))
    fake_pwd = MagicMock()
    fake_pwd.getpwnam.return_value = _FakePw()
    monkeypatch.setitem(sys.modules, "pwd", fake_pwd)
    monkeypatch.delenv("MERGECRAFT_AGENT_USER", raising=False)


# ---------------------------------------------------------------------------
# spawn_agent_cli (shared.py) — covers Codex/Gemini/Claude's primary path,
# OpenCode's cli-fallback streaming path
# ---------------------------------------------------------------------------


def test_spawn_agent_cli_redirects_home_under_privilege_drop(monkeypatch: MonkeyPatch) -> None:
    _simulate_root_privilege_drop(monkeypatch)

    captured: dict[str, Any] = {}

    def _fake_popen(cmd: list[str], **kwargs: object) -> object:
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return MagicMock()

    import mergecraft.agents.shared as shared_module

    monkeypatch.setattr(shared_module.subprocess, "Popen", _fake_popen)

    env = {"HOME": "/github/home", "USER": "root", "LOGNAME": "root", "PATH": "/usr/bin"}
    spawn_agent_cli(["codex", "exec"], env=env)

    assert captured["cmd"][0] == "setpriv", "argv must still be setpriv-wrapped"
    resolved_env = captured["kwargs"]["env"]
    assert resolved_env["HOME"] == "/home/mergecraft"
    assert resolved_env["USER"] == "mergecraft"
    assert resolved_env["LOGNAME"] == "mergecraft"
    assert resolved_env["PATH"] == "/usr/bin"
    # The caller's original env dict must not be mutated in place.
    assert env["HOME"] == "/github/home"


def test_spawn_agent_cli_leaves_env_untouched_when_not_root(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(privilege_module.os, "getuid", lambda: 501)

    captured: dict[str, Any] = {}

    def _fake_popen(cmd: list[str], **kwargs: object) -> object:
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return MagicMock()

    import mergecraft.agents.shared as shared_module

    monkeypatch.setattr(shared_module.subprocess, "Popen", _fake_popen)

    env = {"HOME": "/Users/dev", "PATH": "/usr/bin"}
    spawn_agent_cli(["codex", "exec"], env=env)

    assert captured["cmd"] == ["codex", "exec"]
    assert captured["kwargs"]["env"] == env


# ---------------------------------------------------------------------------
# opencode.py::_boot_opencode_server — the bypass directly implicated in the
# observed "opencode serve exited early: EACCES ... mkdir '/github/home/.local'"
# ---------------------------------------------------------------------------


def test_boot_opencode_server_redirects_home_under_privilege_drop(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _simulate_root_privilege_drop(monkeypatch)

    captured: dict[str, Any] = {}

    class _FakeProc:
        def __init__(self) -> None:
            self.pid = 4242
            self.stdout = self
            self.stderr = self
            self._lines = [b"listening on http://127.0.0.1:12345\n"]

        def poll(self) -> None:
            return None

        def readline(self) -> bytes:
            return self._lines.pop(0) if self._lines else b""

        def read(self) -> bytes:
            return b""

    def _fake_popen(cmd: list[str], **kwargs: object) -> object:
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeProc()

    monkeypatch.setattr(opencode_module.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(opencode_module, "register_process_group", lambda _pid: None)

    env = {"HOME": "/github/home", "PATH": "/usr/bin"}
    handle = opencode_module._boot_opencode_server(
        cli="/usr/bin/opencode", env=env, cwd=str(tmp_path)
    )

    assert captured["cmd"][0] == "setpriv"
    resolved_env = captured["kwargs"]["env"]
    assert resolved_env["HOME"] == "/home/mergecraft"
    assert resolved_env["USER"] == "mergecraft"
    assert handle.base_url == "http://127.0.0.1:12345"


# ---------------------------------------------------------------------------
# claude.py::_run_claude_legacy_subprocess — the FileNotFoundError fallback
# ---------------------------------------------------------------------------


def test_claude_legacy_subprocess_redirects_home_under_privilege_drop(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _simulate_root_privilege_drop(monkeypatch)

    captured: dict[str, Any] = {}

    def _fake_run(cmd: list[str], **kwargs: object) -> object:
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(claude_module.subprocess, "run", _fake_run)
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "0")

    ctx = make_agent_run_context(tmp_path, resolved_model="claude-sonnet")
    result = claude_module._run_claude_legacy_subprocess(
        cmd=["claude", "--print"],
        ctx=ctx,
        model="claude-sonnet",
        skip_permissions=False,
    )

    assert captured["cmd"][0] == "setpriv"
    resolved_env = captured["kwargs"]["env"]
    assert resolved_env["HOME"] == "/home/mergecraft"
    assert resolved_env["USER"] == "mergecraft"
    assert resolved_env["LOGNAME"] == "mergecraft"
    assert result.success is True


# ---------------------------------------------------------------------------
# codex.py::_build_env — $CODEX_HOME is not $HOME; it needs its own chown
# ---------------------------------------------------------------------------


def test_build_env_chowns_codex_home_under_privilege_drop(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _simulate_root_privilege_drop(monkeypatch)

    captured: dict[str, Any] = {}

    def _fake_chown_run(cmd: list[str], **kwargs: object) -> object:
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return MagicMock(returncode=0)

    monkeypatch.setattr(privilege_module.subprocess, "run", _fake_chown_run)
    monkeypatch.delenv("CODEX_AUTH_JSON", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # _codex_home()'s fallback chain (RUNNER_TEMP / GITHUB_WORKSPACE / the
    # real shared ~/.cache/mergecraft) touches the real filesystem outside
    # tmp_path whenever ctx.tmpdir resolves under a forbidden temp root —
    # true on real CI, where pytest's tmp_path lives under /tmp. Pin the
    # first-checked override so this test's mkdir stays inside tmp_path
    # regardless of platform/CI, instead of racing other tests for the
    # real, unisolated ~/.cache/mergecraft directory.
    monkeypatch.setenv("MERGECRAFT_CODEX_HOME_PARENT", str(tmp_path / "codex-home-parent"))

    ctx = make_agent_run_context(tmp_path, resolved_model="gpt-5.6-sol")
    env = codex_module._build_env(ctx)

    assert captured["cmd"][0] == "chown"
    assert captured["cmd"][1] == "-R"
    assert captured["cmd"][2] == "1001:1001"
    codex_home = codex_module._codex_home(ctx)
    assert captured["cmd"][3] == str(codex_home)
    assert env["CODEX_HOME"] == str(codex_home)


def test_build_env_does_not_chown_when_not_root(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(privilege_module.os, "getuid", lambda: 501)

    called: list[list[str]] = []

    def _fake_run(cmd: list[str], **kwargs: object) -> object:
        called.append(cmd)
        return MagicMock(returncode=0)

    monkeypatch.setattr(privilege_module.subprocess, "run", _fake_run)
    monkeypatch.delenv("CODEX_AUTH_JSON", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # _build_env() calls _codex_home() unconditionally, before the root
    # check — pin the fallback parent to tmp_path here too (see the sibling
    # root-path test's comment for why).
    monkeypatch.setenv("MERGECRAFT_CODEX_HOME_PARENT", str(tmp_path / "codex-home-parent"))

    ctx = make_agent_run_context(tmp_path, resolved_model="gpt-5.6-sol")
    codex_module._build_env(ctx)

    assert called == []


# ---------------------------------------------------------------------------
# gemini.py::write_mcp_config — same bug class, unobserved only because this
# repo's self-review doesn't route through Gemini
# ---------------------------------------------------------------------------


def test_gemini_write_mcp_config_chowns_gemini_home_under_privilege_drop(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _simulate_root_privilege_drop(monkeypatch)

    captured: dict[str, Any] = {}

    def _fake_chown_run(cmd: list[str], **kwargs: object) -> object:
        captured["cmd"] = cmd
        return MagicMock(returncode=0)

    monkeypatch.setattr(privilege_module.subprocess, "run", _fake_chown_run)

    ctx = make_agent_run_context(tmp_path, resolved_model="gemini-pro")
    gemini_module.write_mcp_config(ctx)

    assert captured["cmd"][0] == "chown"
    assert captured["cmd"][2] == "1001:1001"
    assert captured["cmd"][3] == str(gemini_module._gemini_home(ctx))


def test_gemini_write_mcp_config_does_not_chown_when_not_root(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(privilege_module.os, "getuid", lambda: 501)

    called: list[list[str]] = []
    monkeypatch.setattr(
        privilege_module.subprocess, "run", lambda cmd, **kw: called.append(cmd) or MagicMock()
    )

    ctx = make_agent_run_context(tmp_path, resolved_model="gemini-pro")
    gemini_module.write_mcp_config(ctx)

    assert called == []


# ---------------------------------------------------------------------------
# claude.py::write_mcp_config — same bug class again; ctx.tmpdir itself is
# chowned at creation, but a subdirectory root creates under it is not
# ---------------------------------------------------------------------------


def test_claude_write_mcp_config_chowns_config_dir_under_privilege_drop(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _simulate_root_privilege_drop(monkeypatch)

    captured: dict[str, Any] = {}

    def _fake_chown_run(cmd: list[str], **kwargs: object) -> object:
        captured["cmd"] = cmd
        return MagicMock(returncode=0)

    monkeypatch.setattr(privilege_module.subprocess, "run", _fake_chown_run)

    ctx = make_agent_run_context(tmp_path, resolved_model="claude-sonnet")
    claude_module.write_mcp_config(ctx)

    assert captured["cmd"][0] == "chown"
    assert captured["cmd"][2] == "1001:1001"
    assert captured["cmd"][3] == str(tmp_path / ".claude")


def test_claude_write_mcp_config_does_not_chown_when_not_root(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(privilege_module.os, "getuid", lambda: 501)

    called: list[list[str]] = []
    monkeypatch.setattr(
        privilege_module.subprocess, "run", lambda cmd, **kw: called.append(cmd) or MagicMock()
    )

    ctx = make_agent_run_context(tmp_path, resolved_model="claude-sonnet")
    claude_module.write_mcp_config(ctx)

    assert called == []
