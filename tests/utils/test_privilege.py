"""Direct unit coverage for agent privilege drop helpers (W3.4)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

import mergecraft.utils.privilege as privilege
from mergecraft.agents.shared import wrap_agent_subprocess
from mergecraft.utils.privilege import (
    agent_user_name,
    prepare_workspace_for_agent,
    wrap_agent_command,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def test_agent_user_name_default(monkeypatch: MonkeyPatch) -> None:
    """Direct ``agent_user_name`` — defaults to ``mergecraft`` when unset/blank."""
    monkeypatch.delenv("MERGECRAFT_AGENT_USER", raising=False)
    assert agent_user_name() == "mergecraft"
    monkeypatch.setenv("MERGECRAFT_AGENT_USER", "   ")
    assert agent_user_name() == "mergecraft"


def test_agent_user_name_env_override(monkeypatch: MonkeyPatch) -> None:
    """Direct ``agent_user_name`` — ``MERGECRAFT_AGENT_USER`` wins when non-blank."""
    monkeypatch.setenv("MERGECRAFT_AGENT_USER", "runner-agent")
    assert agent_user_name() == "runner-agent"


def test_wrap_agent_command_noop_when_not_root(monkeypatch: MonkeyPatch) -> None:
    """Direct ``wrap_agent_command`` — non-root hosts keep argv unchanged (darwin)."""
    monkeypatch.setattr(privilege.os, "getuid", lambda: 501)
    cmd = ["claude", "--print"]
    assert wrap_agent_command(cmd) == cmd


def test_wrap_agent_command_prefixes_setpriv_when_root(
    monkeypatch: MonkeyPatch,
) -> None:
    """Direct ``wrap_agent_command`` — root + setpriv wraps argv for the agent user.

    Fails if the privilege drop is deleted: returned argv equals the bare cmd.
    Runtime UID≠0 proof stays deferred to W11 in-image; this pins structure.
    """
    import sys

    class _Pw:
        pw_uid = 1001
        pw_gid = 1001

    fake_pwd = MagicMock()
    fake_pwd.getpwnam.return_value = _Pw()
    monkeypatch.setitem(sys.modules, "pwd", fake_pwd)
    monkeypatch.setattr(privilege.os, "getuid", lambda: 0)
    monkeypatch.setattr(privilege.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setenv("MERGECRAFT_AGENT_USER", "mergecraft")
    wrapped = wrap_agent_command(["codex", "exec"])
    assert wrapped[0] == "setpriv", "root agent spawn must go through setpriv"
    assert "--reuid=mergecraft" in wrapped
    assert "--regid=mergecraft" in wrapped
    assert "--init-groups" in wrapped
    assert wrapped[-2:] == ["codex", "exec"]


def test_wrap_agent_command_skips_setpriv_when_missing(
    monkeypatch: MonkeyPatch,
) -> None:
    """Direct ``wrap_agent_command`` — root without setpriv fails closed (F4' fix).

    Previously this test pinned the fail-open default (returning the bare
    command so the agent ran as root). S2 inverts that: a missing ``setpriv``
    is now a configuration error, surfaced via ``main._ConfigurationError``.
    """
    from mergecraft.main import _ConfigurationError

    monkeypatch.setattr(privilege.os, "getuid", lambda: 0)
    monkeypatch.setattr(privilege.shutil, "which", lambda _name: None)
    with pytest.raises(_ConfigurationError, match="setpriv"):
        wrap_agent_command(["gemini", "run"])


def test_wrap_agent_subprocess_delegates_to_wrap_agent_command(
    monkeypatch: MonkeyPatch,
) -> None:
    """Direct ``wrap_agent_subprocess`` — agent spawn sites must go through this helper.

    Fails if the shared wrapper is deleted or bypasses ``wrap_agent_command``.
    """
    import sys

    class _Pw:
        pw_uid = 1001
        pw_gid = 1001

    fake_pwd = MagicMock()
    fake_pwd.getpwnam.return_value = _Pw()
    monkeypatch.setitem(sys.modules, "pwd", fake_pwd)
    monkeypatch.setattr(privilege.os, "getuid", lambda: 0)
    monkeypatch.setattr(privilege.shutil, "which", lambda name: f"/usr/bin/{name}")
    wrapped = wrap_agent_subprocess(["opencode", "serve"])
    assert wrapped[0] == "setpriv"
    assert wrapped[-2:] == ["opencode", "serve"]


def test_prepare_workspace_for_agent_noop_when_not_root(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Direct ``prepare_workspace_for_agent`` — non-root is a no-op (no chown)."""
    calls: list[object] = []
    monkeypatch.setattr(privilege.os, "getuid", lambda: 501)
    monkeypatch.setattr(
        privilege.subprocess,
        "run",
        lambda *a, **k: calls.append((a, k)) or MagicMock(returncode=0),
    )
    prepare_workspace_for_agent(str(tmp_path))
    assert calls == []


def test_prepare_workspace_for_agent_chowns_when_root(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Direct ``prepare_workspace_for_agent`` — root chowns workspace for agent user.

    Fails if chown is deleted: no subprocess invocation is recorded.
    """
    import sys

    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs: object) -> object:
        calls.append(list(cmd))
        return MagicMock(returncode=0)

    class _Pw:
        pw_uid = 1001
        pw_gid = 1001

    fake_pwd = MagicMock()
    fake_pwd.getpwnam.return_value = _Pw()
    monkeypatch.setattr(privilege.os, "getuid", lambda: 0)
    monkeypatch.setenv("MERGECRAFT_AGENT_USER", "mergecraft")
    monkeypatch.setitem(sys.modules, "pwd", fake_pwd)
    monkeypatch.setattr(privilege.subprocess, "run", _fake_run)

    prepare_workspace_for_agent(str(tmp_path))

    assert calls, "prepare_workspace_for_agent must chown when root"
    assert calls[0][0] == "chown"
    assert calls[0][1] == "-R"
    assert calls[0][2] == "1001:1001"
    assert calls[0][3] == str(tmp_path)
