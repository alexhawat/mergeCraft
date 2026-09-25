"""In-image proof that the runtime tree is root-owned (S8).

The action runs as root and imports ``/opt/mergecraft``; the agent user it drops
to must not be able to rewrite that tree, while the agent's own ``HOME`` must
stay writable. On a host without euid 0, Linux, ``unshare`` and ``setpriv`` the
whole module skips with the precondition reason; it runs as root inside the
image.
"""

from __future__ import annotations

import os
import pwd
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT_PRECONDITION_REASON = "requires euid 0, Linux, unshare and setpriv — runs in the action image"

_RUNTIME_TREE = Path("/opt/mergecraft")


def _preconditions_met() -> bool:
    if sys.platform != "linux" or os.geteuid() != 0:
        return False
    if not _RUNTIME_TREE.is_dir():
        return False
    user = os.environ.get("MERGECRAFT_AGENT_USER", "mergecraft").strip() or "mergecraft"
    try:
        pwd.getpwnam(user)
    except KeyError:
        return False
    return shutil.which("unshare") is not None and shutil.which("setpriv") is not None


pytestmark = pytest.mark.skipif(not _preconditions_met(), reason=_ROOT_PRECONDITION_REASON)


def _agent_user() -> str:
    return os.environ.get("MERGECRAFT_AGENT_USER", "mergecraft").strip() or "mergecraft"


def _as_agent(script: str) -> subprocess.CompletedProcess[str]:
    entry = pwd.getpwnam(_agent_user())
    return subprocess.run(
        [
            "setpriv",
            f"--reuid={entry.pw_uid}",
            f"--regid={entry.pw_gid}",
            "--clear-groups",
            "bash",
            "-c",
            script,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_runtime_tree_and_venv_are_owned_by_root() -> None:
    assert _RUNTIME_TREE.stat().st_uid == 0, f"{_RUNTIME_TREE} must be root-owned"
    venv = _RUNTIME_TREE / ".venv"
    assert venv.is_dir(), f"missing {venv}"
    assert venv.stat().st_uid == 0, f"{venv} must be root-owned"


def test_agent_user_cannot_write_the_runtime_tree() -> None:
    result = _as_agent("test -w /opt/mergecraft && echo WRITABLE || echo READONLY")
    assert "READONLY" in result.stdout, (
        f"the agent user must not write /opt/mergecraft: {result.stdout!r} {result.stderr!r}"
    )


def test_agent_home_is_writable() -> None:
    home = Path(pwd.getpwnam(_agent_user()).pw_dir)
    probe = home / ".mergecraft-write-probe"
    result = _as_agent(f"touch {probe} && echo HOME_OK || echo HOME_DENIED")
    try:
        assert "HOME_OK" in result.stdout, (
            f"{home} must be writable by the agent user: {result.stdout!r} {result.stderr!r}"
        )
        assert probe.exists()
    finally:
        probe.unlink(missing_ok=True)
