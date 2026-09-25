"""Lane A AP1.3 — sudo argv must not carry secret values (MCB-08 / D9).

Also pins the privilege drop the namespace shell installs after its masks: a
root orchestrator drops to the agent user, a sudo-elevated shell drops back to
the orchestrator's own numeric UID/GID, and a host without either refuses
before any process is spawned.
"""

from __future__ import annotations

import os
import pwd
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from mergecraft.mcp import shell as shell_mod
from mergecraft.utils import privilege
from mergecraft.utils.secrets import PROVIDER_KEY_ENV_VARS

_CANARY = "CANARY_PROVIDER_SECRET_VALUE_AP1"


class _FakePwEntry:
    """Minimal ``pwd.struct_passwd`` stand-in for the drop target."""

    def __init__(self, name: str = "mergecraft", uid: int = 10001, gid: int = 10001) -> None:
        self.pw_name = name
        self.pw_uid = uid
        self.pw_gid = gid


def _fake_drop_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``setpriv`` and the agent user resolvable regardless of host."""
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(pwd, "getpwnam", lambda name: _FakePwEntry(name))
    monkeypatch.setattr(privilege, "_in_action_image", lambda: True)
    monkeypatch.setattr(privilege, "_setpriv_supports_bounding_set", lambda: True)


def _capture_popen_argv(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    captured: list[str] = []

    def _popen(argv: list[str], **_kwargs: Any) -> MagicMock:
        captured.extend(argv)
        return MagicMock()

    monkeypatch.setattr(shell_mod.subprocess, "Popen", _popen)
    return captured


def _spawn(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    *,
    cwd: str,
    isolate_network: bool = False,
) -> list[str]:
    captured = _capture_popen_argv(monkeypatch)
    shell_mod._spawn_shell(
        command,
        env={"PATH": "/usr/bin:/bin"},
        cwd=cwd,
        stdout=MagicMock(),
        stderr=MagicMock(),
        isolate_network=isolate_network,
    )
    return captured


def test_root_unshare_shell_drops_identity_after_every_mount(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The payload is the last exec of the mask script, under ``setpriv``."""
    monkeypatch.setattr(os, "getuid", lambda: 0)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    _fake_drop_tools(monkeypatch)
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "unshare")
    monkeypatch.setattr(shell_mod, "network_namespace_available", lambda: False)

    argv = _spawn(monkeypatch, "echo ok", cwd=str(tmp_path))
    assert argv[:4] == ["unshare", "--pid", "--fork", "--mount-proc"]
    wrapped = argv[-1]
    before_drop, marker, after_drop = wrapped.partition("exec setpriv")
    assert marker, f"the root shell payload must exec setpriv; got {wrapped!r}"
    # Every mask is installed before the identity is dropped in the same exec.
    assert "mount --bind" in before_drop, wrapped
    assert "mount -t tmpfs" in before_drop, wrapped
    assert "docker.sock" in before_drop, wrapped
    for flag in (
        "--no-new-privs",
        "--inh-caps=-all",
        "--ambient-caps=-all",
        "--bounding-set=-all",
        "--reuid=mergecraft",
        "--regid=mergecraft",
        "--init-groups",
    ):
        assert flag in after_drop, f"missing {flag} in {after_drop!r}"
    assert after_drop.endswith(" -- bash --noprofile --norc -c 'echo ok'"), after_drop


def test_sudo_unshare_shell_drops_to_the_orchestrator_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A non-root orchestrator that elevated through sudo drops back to itself."""
    monkeypatch.setattr(os, "getuid", lambda: 4242)
    monkeypatch.setattr(os, "geteuid", lambda: 4242)
    monkeypatch.setattr(os, "getgid", lambda: 4343)
    _fake_drop_tools(monkeypatch)
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "sudo-unshare")
    monkeypatch.setattr(shell_mod, "network_namespace_available", lambda: False)

    argv = _spawn(monkeypatch, "echo ok", cwd=str(tmp_path))
    assert argv[0] == "sudo"
    wrapped = argv[-1]
    assert "exec setpriv" in wrapped, wrapped
    assert "--reuid=4242" in wrapped, wrapped
    assert "--regid=4343" in wrapped, wrapped
    assert "--clear-groups" in wrapped, wrapped
    assert "--init-groups" not in wrapped, wrapped


def test_missing_setpriv_refuses_before_spawning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without ``setpriv`` the shell must fail closed, not run as root."""
    from mergecraft.main import _ConfigurationError

    monkeypatch.setattr(os, "getuid", lambda: 0)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "setpriv" else "/bin/true")
    monkeypatch.setattr(pwd, "getpwnam", lambda name: _FakePwEntry(name))
    monkeypatch.setattr(privilege, "_in_action_image", lambda: True)
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "unshare")
    monkeypatch.setattr(shell_mod, "network_namespace_available", lambda: False)

    spawned: list[object] = []

    def _popen(*args: object, **kwargs: object) -> MagicMock:
        spawned.append(args)
        return MagicMock()

    monkeypatch.setattr(shell_mod.subprocess, "Popen", _popen)
    with pytest.raises(_ConfigurationError, match="setpriv"):
        shell_mod._spawn_shell(
            "echo ok",
            env={},
            cwd=str(tmp_path),
            stdout=MagicMock(),
            stderr=MagicMock(),
        )
    assert spawned == [], "the shell must not spawn without a resolvable privilege drop"


def test_unresolvable_agent_user_refuses_before_spawning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A user missing from the passwd database is a configuration error."""
    from mergecraft.main import _ConfigurationError

    monkeypatch.setattr(os, "getuid", lambda: 0)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(pwd, "getpwnam", lambda name: (_ for _ in ()).throw(KeyError(name)))
    monkeypatch.setattr(privilege, "_in_action_image", lambda: True)
    monkeypatch.setattr(privilege, "_setpriv_supports_bounding_set", lambda: True)
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "unshare")
    monkeypatch.setattr(shell_mod, "network_namespace_available", lambda: False)

    spawned: list[object] = []

    def _popen(*args: object, **kwargs: object) -> MagicMock:
        spawned.append(args)
        return MagicMock()

    monkeypatch.setattr(shell_mod.subprocess, "Popen", _popen)
    with pytest.raises(_ConfigurationError, match="mergecraft"):
        shell_mod._spawn_shell(
            "echo ok",
            env={},
            cwd=str(tmp_path),
            stdout=MagicMock(),
            stderr=MagicMock(),
        )
    assert spawned == [], "the shell must not spawn without a resolvable drop target"


def test_sandbox_exec_argv_is_unchanged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Darwin's ``sandbox-exec`` branch keeps its byte-identical argv."""
    from mergecraft.analyzers.sandbox import build_sandbox_exec_argv

    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "sandbox-exec")
    argv = _spawn(monkeypatch, "echo ok", cwd=str(tmp_path))
    expected = build_sandbox_exec_argv(("bash", "-c", "echo ok"), workspace=Path(tmp_path))
    assert argv == expected
    assert "setpriv" not in " ".join(argv)


def test_non_root_unshare_argv_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A non-root direct unshare host keeps today's flat wrapped command."""
    monkeypatch.setattr(os, "getuid", lambda: 4242)
    monkeypatch.setattr(os, "geteuid", lambda: 4242)
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "unshare")
    monkeypatch.setattr(shell_mod, "network_namespace_available", lambda: False)

    argv = _spawn(monkeypatch, "echo ok", cwd=str(tmp_path))
    assert argv[:4] == ["unshare", "--pid", "--fork", "--mount-proc"]
    assert argv[4:6] == ["bash", "-c"]
    wrapped = argv[-1]
    assert "setpriv" not in wrapped
    assert wrapped.endswith("echo ok")


@pytest.fixture(autouse=True)
def _sandbox_sudo_unshare(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "sudo-unshare")
    monkeypatch.setattr(shell_mod, "network_namespace_available", lambda: False)
    shell_mod.reset_detection_cache()


def _env_with_canaries() -> dict[str, str]:
    return {name: _CANARY for name in PROVIDER_KEY_ENV_VARS}


def _capture_argv(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    captured: list[str] = []

    def _popen(argv: list[str], **_kwargs: Any) -> MagicMock:
        captured.extend(argv)
        return MagicMock()

    monkeypatch.setattr(shell_mod.subprocess, "Popen", _popen)
    return captured


@pytest.mark.parametrize(
    "isolate_network",
    [
        False,
        True,
    ],
    ids=["pid_only", "pid_and_net"],
)
def test_no_provider_key_value_appears_in_any_branch_argv(
    monkeypatch: pytest.MonkeyPatch, isolate_network: bool
) -> None:
    # The netns probe is a property of the host, not of argv construction:
    # macOS has no network namespaces and GitHub's runners fail
    # ``unshare --net`` too, so without this stub the isolate_network=True case
    # raises in shell.py:307 before reaching the assertion below. Stubbing it
    # makes the branch reachable and the result host-independent -- which is
    # what let the previous xfail(strict=False) sit here silently either way.
    monkeypatch.setattr(shell_mod, "_network_namespace_available", lambda: True)
    for method in ("unshare", "sudo-unshare", "none"):
        monkeypatch.setenv("MERGECRAFT_ALLOW_UNSANDBOXED_SHELL", "1")
        if method == "unshare":
            monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "unshare")
        elif method == "sudo-unshare":
            monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "sudo-unshare")
        else:
            monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "none")
        captured = _capture_argv(monkeypatch)
        shell_mod._spawn_shell(
            "echo ok",
            env=_env_with_canaries(),
            cwd="/tmp",
            stdout=MagicMock(),
            stderr=MagicMock(),
            isolate_network=isolate_network,
        )
        joined = " ".join(captured)
        assert _CANARY not in joined, f"secret leaked in argv for method={method}"


def test_sudo_branch_uses_preserve_env_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_argv(monkeypatch)
    env = {"ANTHROPIC_API_KEY": "sekret", "PATH": "/usr/bin"}
    shell_mod._spawn_shell(
        "echo ok",
        env=env,
        cwd="/tmp",
        stdout=MagicMock(),
        stderr=MagicMock(),
    )
    assert any(arg.startswith("--preserve-env=") for arg in captured)
    assert not any("=sekret" in arg for arg in captured)
