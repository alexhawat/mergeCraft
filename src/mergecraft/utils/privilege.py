"""Drop agent subprocess privileges while keeping the action entrypoint root (W3.4)."""

from __future__ import annotations

import os
import shutil
import subprocess

from loguru import logger

_DEFAULT_AGENT_USER = "mergecraft"


def agent_user_name() -> str:
    return (
        os.environ.get("MERGECRAFT_AGENT_USER", _DEFAULT_AGENT_USER).strip() or _DEFAULT_AGENT_USER
    )


def wrap_agent_command(cmd: list[str]) -> list[str]:
    """Prefix ``cmd`` with ``setpriv`` when running as root in the action image."""
    if os.getuid() != 0:
        return list(cmd)
    user = agent_user_name()
    if shutil.which("setpriv") is None:
        logger.debug("setpriv unavailable; agent subprocess runs as uid {}", os.getuid())
        return list(cmd)
    return ["setpriv", f"--reuid={user}", f"--regid={user}", "--init-groups", *cmd]


def prepare_workspace_for_agent(workspace: str) -> None:
    """``chown`` the checkout workspace so the unprivileged agent user can operate (W3.4)."""
    if os.getuid() != 0:
        return
    user = agent_user_name()
    try:
        import pwd

        pw = pwd.getpwnam(user)
    except ImportError, KeyError:
        logger.debug("agent user {!r} not found; skipping workspace chown", user)
        return
    target = workspace.strip()
    if not target:
        return
    subprocess.run(
        ["chown", "-R", f"{pw.pw_uid}:{pw.pw_gid}", target],
        check=False,
        capture_output=True,
        text=True,
    )
    logger.debug("chowned workspace {} for agent user {}", target, user)


__all__ = ["agent_user_name", "prepare_workspace_for_agent", "wrap_agent_command"]
