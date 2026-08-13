"""Drop agent subprocess privileges while keeping the action entrypoint root (W3.4).

When the action image runs as root the agent subprocess must drop to the
unprivileged ``mergecraft`` user via ``setpriv``. If the boundary is missing
(``setpriv`` not on PATH, the user not in the passwd database, or the resolved
user has UID/GID 0) the run aborts as a configuration error rather than
silently executing the agent as root — that fallback is the F4' defect and it
must not regress. UID/GID 0 is the security boundary, not the username: a
configured user that happens to resolve to ``root`` would still spawn the
agent as root.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import TYPE_CHECKING

from loguru import logger

_DEFAULT_AGENT_USER = "mergecraft"

if TYPE_CHECKING:
    # Imported lazily inside the failure paths to avoid a circular import:
    # ``mergecraft.main`` already imports ``prepare_workspace_for_agent`` from
    # this module, so the class symbol is looked up at raise-time only.
    from mergecraft.main import _ConfigurationError


def agent_user_name() -> str:
    return (
        os.environ.get("MERGECRAFT_AGENT_USER", _DEFAULT_AGENT_USER).strip() or _DEFAULT_AGENT_USER
    )


def _raise_configuration_error(message: str) -> _ConfigurationError:
    """Return a ``main._ConfigurationError`` instance, importing lazily.

    The deferred import keeps the dependency direction one-way
    (``main`` → ``utils``) while letting the failure surface the same
    exception type ``_classify_error_outcome`` already maps to
    ``RunOutcome.configuration_error``.
    """
    from mergecraft.main import _ConfigurationError

    return _ConfigurationError(message)


def wrap_agent_command(cmd: list[str]) -> list[str]:
    """Prefix ``cmd`` with ``setpriv`` when running as root in the action image.

    Fails closed with ``main._ConfigurationError`` if ``setpriv`` or the agent
    user is unavailable — never silently returns the unwrapped command (the
    F4' fail-open default this contract replaces). Resolves the user record via
    ``pwd.getpwnam`` and additionally rejects UID/GID 0 — the username is not
    the security boundary; a configured user that happens to resolve to ``root``
    would still spawn the agent as root, defeating the privilege drop.
    """
    if os.getuid() != 0:
        return list(cmd)
    user = agent_user_name()
    if shutil.which("setpriv") is None:
        logger.error(
            "setpriv unavailable on PATH; refusing to run the agent subprocess as root "
            "(uid={}) — image must ship setpriv so the privilege drop can land",
            os.getuid(),
        )
        raise _raise_configuration_error(
            "setpriv is not on PATH inside the action image; the agent privilege drop "
            "is unavailable and the run cannot proceed as root"
        )
    try:
        import pwd

        entry = pwd.getpwnam(user)
    except ImportError as exc:
        # ``ImportError`` on a non-POSIX platform — the action image is Linux,
        # so this branch cannot fire there; surface as a config error rather than
        # silently continuing, since it would otherwise look identical to the
        # fail-open case to anyone reading logs.
        logger.error("pwd module unavailable; cannot verify agent user {} on this platform", user)
        raise _raise_configuration_error(
            f"pwd module unavailable; cannot verify agent user {user!r} on this platform"
        ) from exc
    except KeyError as exc:
        logger.error(
            "agent user {!r} is not in /etc/passwd; refusing to run the agent "
            "subprocess as root — Dockerfile must useradd this uid before shipping",
            user,
        )
        raise _raise_configuration_error(
            f"agent user {user!r} does not exist in /etc/passwd inside the action "
            f"image; the privilege drop cannot land and the run cannot proceed as root"
        ) from exc
    if entry.pw_uid == 0 or entry.pw_gid == 0:
        logger.error(
            "agent user {!r} resolves to uid={} gid={}; refusing to run the agent "
            "subprocess as root — privilege drop requires a non-zero uid/gid",
            entry.pw_name,
            entry.pw_uid,
            entry.pw_gid,
        )
        raise _raise_configuration_error(
            f"agent user {entry.pw_name!r} resolves to uid={entry.pw_uid} gid={entry.pw_gid} "
            f"inside the action image; the privilege drop cannot land onto a root account "
            f"and the run cannot proceed"
        )
    return ["setpriv", f"--reuid={user}", f"--regid={user}", "--init-groups", *cmd]


def prepare_workspace_for_agent(workspace: str) -> None:
    """``chown`` the checkout workspace so the unprivileged agent user can operate (W3.4).

    On non-POSIX hosts (where ``pwd`` cannot be imported at all) the action
    image cannot be running, so the missing-user branch is silent. When the
    ``pwd`` module **is** importable but the user genuinely does not exist, the
    run fails closed as a configuration error — the previous
    ``except (ImportError, KeyError): return`` collapsed the two and let a
    missing user pass silently. Resolves the user record and additionally
    rejects UID/GID 0: a configured user that maps to ``root`` would still
    leave the chown at uid 0, which is not the privilege drop this helper
    exists to perform.
    """
    if os.getuid() != 0:
        return
    user = agent_user_name()
    try:
        import pwd

        pw = pwd.getpwnam(user)
    except ImportError:
        logger.debug("pwd module unavailable; skipping workspace chown on this platform")
        return
    except KeyError as exc:
        logger.error(
            "agent user {!r} is not in /etc/passwd; cannot chown the workspace for the "
            "privilege drop — aborting instead of running the agent as root",
            user,
        )
        raise _raise_configuration_error(
            f"agent user {user!r} does not exist in /etc/passwd inside the action image; "
            f"prepare_workspace_for_agent cannot chown {workspace!r} for the privilege drop"
        ) from exc
    if pw.pw_uid == 0 or pw.pw_gid == 0:
        logger.error(
            "agent user {!r} resolves to uid={} gid={}; refusing to chown the workspace "
            "for a root account — privilege drop requires a non-zero uid/gid",
            pw.pw_name,
            pw.pw_uid,
            pw.pw_gid,
        )
        raise _raise_configuration_error(
            f"agent user {pw.pw_name!r} resolves to uid={pw.pw_uid} gid={pw.pw_gid} "
            f"inside the action image; prepare_workspace_for_agent cannot chown "
            f"{workspace!r} onto a root account"
        )
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
