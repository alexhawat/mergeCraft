"""Supervised subprocesses for the dependency prep phase.

Every install command heads its own session (``start_new_session=True``) and is
registered in the process-group registry for its lifetime, so the run's outer
timeout handler (``kill_all_active_process_groups``) reaches it, and a cancelled
command (the prep deadline, or the run stopping prep) has its whole tree killed
TERM -> grace -> KILL before the cancellation propagates.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from mergecraft.utils.process_group import (
    kill_process_group,
    register_process_group,
    unregister_process_group,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_REAP_TIMEOUT_S = 5.0


async def run_prep_command(
    cmd: str,
    args: list[str],
    *,
    env: Mapping[str, str],
    cwd: Path | None = None,
) -> tuple[int, str]:
    """Run one prep command; return ``(returncode, combined output)``.

    Cancellation kills the command's process group and reaps the leader before
    re-raising, so no install outlives the prep phase that started it.
    """
    proc = await asyncio.create_subprocess_exec(
        cmd,
        *args,
        cwd=str(cwd) if cwd is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=dict(env),
        start_new_session=True,
    )
    register_process_group(proc.pid)
    try:
        stdout_b, stderr_b = await proc.communicate()
    except BaseException:
        await asyncio.to_thread(kill_process_group, proc.pid)
        with contextlib.suppress(BaseException):
            await asyncio.wait_for(proc.wait(), timeout=_REAP_TIMEOUT_S)
        raise
    finally:
        unregister_process_group(proc.pid)
    out = b"\n".join(part for part in (stdout_b, stderr_b) if part).decode(
        "utf-8", errors="replace"
    )
    returncode = proc.returncode if proc.returncode is not None else -1
    return returncode, out.strip()


__all__ = ["run_prep_command"]
