"""An analyzer timeout kills the whole process group, not just the direct child."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from mergecraft.analyzers.run import _run_subprocess

if TYPE_CHECKING:
    from pathlib import Path

from mergecraft.analyzers.resolve import AnalyzerPlan


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill(0); read the state when /proc is available.
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            return handle.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return True


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_timeout_kills_grandchildren(tmp_path: Path) -> None:
    pidfile = tmp_path / "grandchild.pid"
    script = f"sleep 30 & echo $! > {pidfile}; sleep 30"
    plan = AnalyzerPlan(manifest_id="probe", argv=("sh",), cwd=tmp_path, mode="native")

    started = time.monotonic()
    outcome = _run_subprocess(
        ["sh", "-c", script],
        plan=plan,
        cwd=tmp_path,
        timeout_s=1,
        preexec_fn=None,
        command="sh",
    )
    assert not isinstance(outcome, subprocess.CompletedProcess)
    assert outcome.status == "timed_out"
    assert time.monotonic() - started < 15

    grandchild = int(pidfile.read_text(encoding="utf-8").strip())
    deadline = time.monotonic() + 3
    while _alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(grandchild), "grandchild survived the analyzer timeout"
