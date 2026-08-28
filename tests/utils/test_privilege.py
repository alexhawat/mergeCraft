"""Direct unit coverage for agent privilege drop helpers (W3.4)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

import mergecraft.utils.privilege as privilege
from mergecraft.agents.shared import wrap_agent_subprocess
from mergecraft.utils.privilege import (
    agent_subprocess_env,
    agent_user_name,
    prepare_workspace_for_agent,
    wrap_agent_command,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def _force_action_image_root(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(privilege.os, "getuid", lambda: 0)
    monkeypatch.setattr(privilege, "_in_action_image", lambda: True)
    monkeypatch.setattr(privilege, "_setpriv_supports_bounding_set", lambda: True)


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
    _force_action_image_root(monkeypatch)
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

    _force_action_image_root(monkeypatch)
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
    _force_action_image_root(monkeypatch)
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
    _force_action_image_root(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_AGENT_USER", "mergecraft")
    monkeypatch.setitem(sys.modules, "pwd", fake_pwd)
    monkeypatch.setattr(privilege.subprocess, "run", _fake_run)

    prepare_workspace_for_agent(str(tmp_path))

    assert calls, "prepare_workspace_for_agent must chown when root"
    assert calls[0][0] == "find"
    assert "chown" in calls[0]
    assert calls[0][-3] == "1001:1001"
    assert calls[0][1] == str(tmp_path)


# ---------------------------------------------------------------------------
# agent_subprocess_env — HOME/USER/LOGNAME redirect (live-bug fix)
# ---------------------------------------------------------------------------


class _PwWithHome:
    """Stand-in ``pwd.struct_passwd`` carrying the fields ``agent_subprocess_env`` reads."""

    def __init__(
        self,
        name: str = "mergecraft",
        uid: int = 1001,
        gid: int = 1001,
        home: str = "/home/mergecraft",
    ) -> None:
        self.pw_name = name
        self.pw_uid = uid
        self.pw_gid = gid
        self.pw_dir = home


def _install_fake_pwd(monkeypatch: MonkeyPatch, entry: _PwWithHome) -> None:
    import sys

    fake_pwd = MagicMock()
    fake_pwd.getpwnam.return_value = entry
    monkeypatch.setitem(sys.modules, "pwd", fake_pwd)


def test_agent_subprocess_env_noop_when_not_root(monkeypatch: MonkeyPatch) -> None:
    """Direct ``agent_subprocess_env`` — non-root hosts get an unchanged copy back."""
    monkeypatch.setattr(privilege.os, "getuid", lambda: 501)
    env = {"HOME": "/github/home", "PATH": "/usr/bin"}
    out = agent_subprocess_env(env)
    assert out == env
    assert out is not env, "must return a copy, never the same dict object"


def test_agent_subprocess_env_redirects_inherited_home_when_root(
    monkeypatch: MonkeyPatch,
) -> None:
    """Root + HOME not owned by the agent uid → HOME/USER/LOGNAME are redirected.

    This is the live bug: the container sets ``HOME=/github/home`` (owned by
    the runner's original uid), setpriv drops uid/gid but not HOME, and the
    agent CLI then hits EACCES trying to write dotfiles under it.
    """
    _force_action_image_root(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_AGENT_USER", "mergecraft")
    _install_fake_pwd(monkeypatch, _PwWithHome())
    # /github/home is not owned by uid 1001 in this scenario.
    monkeypatch.setattr(privilege.os, "stat", lambda _path: MagicMock(st_uid=0))

    env = {"HOME": "/github/home", "USER": "root", "LOGNAME": "root", "PATH": "/usr/bin"}
    out = agent_subprocess_env(env)

    assert out["HOME"] == "/home/mergecraft"
    assert out["USER"] == "mergecraft"
    assert out["LOGNAME"] == "mergecraft"
    assert out["PATH"] == "/usr/bin", "unrelated keys must pass through untouched"
    assert env["HOME"] == "/github/home", "input dict must not be mutated"


def test_agent_subprocess_env_preserves_home_already_owned_by_agent_user(
    monkeypatch: MonkeyPatch,
) -> None:
    """A HOME the driver already pointed at a pre-chowned scratch dir is left alone.

    Gemini's driver sets ``HOME`` to its own per-run tmpdir (already chowned
    to the agent user by ``git_setup._prepare_temp_dir_for_agent`` so its MCP
    settings.json is discoverable there) — ``agent_subprocess_env`` must not
    clobber that back to the passwd home directory, or Gemini's MCP config
    silently stops resolving under the privilege drop.
    """
    _force_action_image_root(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_AGENT_USER", "mergecraft")
    entry = _PwWithHome()
    _install_fake_pwd(monkeypatch, entry)
    # The driver-chosen HOME is already owned by the resolved agent uid.
    monkeypatch.setattr(privilege.os, "stat", lambda _path: MagicMock(st_uid=entry.pw_uid))

    env = {"HOME": "/tmp/mergecraft-xyz", "PATH": "/usr/bin"}
    out = agent_subprocess_env(env)

    assert out["HOME"] == "/tmp/mergecraft-xyz", "already-owned HOME must survive untouched"
    assert out["USER"] == "mergecraft"
    assert out["LOGNAME"] == "mergecraft"


def test_agent_subprocess_env_fills_missing_home(monkeypatch: MonkeyPatch) -> None:
    """No ``HOME`` key at all → still filled in with the agent user's real home."""
    _force_action_image_root(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_AGENT_USER", "mergecraft")
    _install_fake_pwd(monkeypatch, _PwWithHome())

    out = agent_subprocess_env({"PATH": "/usr/bin"})

    assert out["HOME"] == "/home/mergecraft"


def test_agent_subprocess_env_missing_user_fails_closed(monkeypatch: MonkeyPatch) -> None:
    """Same fail-closed contract as ``wrap_agent_command`` — missing agent user raises."""
    from mergecraft.main import _ConfigurationError

    _force_action_image_root(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_AGENT_USER", "mergecraft")

    import sys

    fake_pwd = MagicMock()

    def _raise_keyerror(_name: str) -> None:
        raise KeyError(_name)

    fake_pwd.getpwnam.side_effect = _raise_keyerror
    monkeypatch.setitem(sys.modules, "pwd", fake_pwd)

    with pytest.raises(_ConfigurationError, match="mergecraft"):
        agent_subprocess_env({"HOME": "/github/home"})


def test_agent_subprocess_env_uid_zero_fails_closed(monkeypatch: MonkeyPatch) -> None:
    """Same fail-closed contract — a user resolving to UID/GID 0 raises, not redirects."""
    from mergecraft.main import _ConfigurationError

    _force_action_image_root(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_AGENT_USER", "mergecraft")
    _install_fake_pwd(monkeypatch, _PwWithHome(uid=0, gid=0))

    with pytest.raises(_ConfigurationError, match="uid=0"):
        agent_subprocess_env({"HOME": "/github/home"})


def test_agent_subprocess_env_custom_agent_user_via_env(monkeypatch: MonkeyPatch) -> None:
    """``MERGECRAFT_AGENT_USER`` drives which pwd entry is resolved, same as ``wrap_agent_command``."""
    _force_action_image_root(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_AGENT_USER", "reviewer")
    _install_fake_pwd(
        monkeypatch, _PwWithHome(name="reviewer", uid=1002, gid=1002, home="/home/reviewer")
    )
    monkeypatch.setattr(privilege.os, "stat", lambda _path: MagicMock(st_uid=0))

    out = agent_subprocess_env({"HOME": "/github/home"})

    assert out["HOME"] == "/home/reviewer"
    assert out["USER"] == "reviewer"
    assert out["LOGNAME"] == "reviewer"
