"""F43 — killed background processes are reaped, not left as zombies."""

from __future__ import annotations

import subprocess
import sys

import pytest

from mergecraft.mcp import server

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")


def _proc_state(pid: int) -> str | None:
    """Return the kernel state letter of *pid* from /proc, or None when it is gone."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            fields = handle.read().rsplit(")", 1)[1].split()
    except OSError:
        return None
    return fields[0]


def test_killed_background_child_is_reaped_not_left_as_a_zombie() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    try:
        server._kill_and_reap_background_pids({proc.pid})

        # A reaped child has no /proc entry at all; an unreaped one shows as "Z".
        assert _proc_state(proc.pid) is None, "killed child was left unreaped"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_reap_tolerates_pids_that_are_not_our_children() -> None:
    # Not our child: waitpid raises ChildProcessError, which must be swallowed.
    # Only the reap step runs here, so no signal reaches a foreign process group.
    server._reap_background_pids({1})
