"""Git identity + askpass configuration for agent runs."""

from __future__ import annotations

import atexit
import contextlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loguru import logger

if TYPE_CHECKING:
    from mergecraft.mcp.tool_state import ToolState
    from mergecraft.types import ShellPermission
    from mergecraft.utils.github import GitHubClient

ShellPerm = Literal["disabled", "restricted", "enabled"]

MERGECRAFT_BOT_EMAIL = "226033991+mergecraft[bot]@users.noreply.github.com"
MERGECRAFT_BOT_NAME = "mergecraft[bot]"

# Codex refuses PATH-alias helper binaries when CODEX_HOME is under these roots
# ("Refusing to create helper binaries under temporary dir /tmp"). Keep the
# mergeCraft run temp (and thus $CODEX_HOME) outside them.
_FORBIDDEN_TEMP_ROOTS = ("/tmp", "/private/tmp", "/var/tmp", "/usr/tmp")

_created_paths: set[str] = set()
_temp_dir: str | None = None
_atexit_registered = False


def _is_under_forbidden_temp(path: Path) -> bool:
    """Return True when ``path`` resolves under a Codex-forbidden temp root."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in _FORBIDDEN_TEMP_ROOTS:
        try:
            resolved.relative_to(Path(root).resolve())
        except ValueError, OSError:
            continue
        else:
            return True
    return False


def _safe_temp_parent() -> Path | None:
    """Prefer a parent Codex accepts for PATH aliases (not world-writable /tmp)."""
    for key in ("MERGECRAFT_TEMP_PARENT", "RUNNER_TEMP"):
        raw = os.environ.get(key, "").strip()
        if not raw:
            continue
        candidate = Path(raw)
        if candidate.is_dir() and not _is_under_forbidden_temp(candidate):
            return candidate
    cache = (
        Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "mergecraft" / "tmp"
    )
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    if _is_under_forbidden_temp(cache):
        return None
    return cache


def register_created_path(path: str) -> None:
    """Record a mergeCraft-owned leak-surface path for scoped wipe (W2.4)."""
    try:
        resolved = str(Path(path).resolve())
    except OSError:
        resolved = path
    _created_paths.add(resolved)


def _register_atexit_cleanup() -> None:
    global _atexit_registered
    if _atexit_registered:
        return
    atexit.register(cleanup_temp_directory)
    _atexit_registered = True


def _secure_overwrite_file(path: Path) -> None:
    """Overwrite file bytes before unlink (W2.3)."""
    try:
        size = path.stat().st_size
    except OSError:
        return
    try:
        with path.open("r+b") as handle:
            handle.write(b"\x00" * size)
            handle.flush()
    except OSError:
        pass


def cleanup_temp_directory() -> None:
    """Remove the run temp dir and scrub credential files (W2.3)."""
    global _temp_dir
    target = _temp_dir or os.environ.get("MERGECRAFT_TEMP_DIR")
    if not target:
        return
    root = Path(target)
    askpass = root / "credentials" / "git-askpass.sh"
    if askpass.is_file():
        _secure_overwrite_file(askpass)
        with contextlib.suppress(OSError):
            askpass.unlink()
    shutil.rmtree(target, ignore_errors=True)
    _temp_dir = None


def create_temp_directory() -> str:
    import tempfile

    parent = _safe_temp_parent()
    shared = (
        tempfile.mkdtemp(prefix="mergecraft-", dir=str(parent))
        if parent is not None
        else tempfile.mkdtemp(prefix="mergecraft-")
    )
    global _temp_dir
    _temp_dir = shared
    os.environ["MERGECRAFT_TEMP_DIR"] = shared
    register_created_path(shared)
    _prepare_temp_dir_for_agent(shared)
    _register_atexit_cleanup()
    logger.info("» created temp dir at {}", shared)
    return shared


def _prepare_temp_dir_for_agent(path: str) -> None:
    """Make the run temp dir traversable by the dropped-UID agent (W3.4 / Final).

    The directory starts as root-owned ``0o700`` from ``mkdtemp``. Agent CLIs
    (Claude MCP config, Codex/Gemini ``HOME``, …) must read and write under it
    after ``setpriv``. Hand the tree to the agent user at ``0o755``. The
    ``credentials/`` askpass subtree is re-locked to root ``0o700`` when written
    (see :func:`write_askpass_script`) so tokens stay out of agent reach.
    """
    if os.getuid() != 0:
        return
    try:
        import pwd

        from mergecraft.utils.privilege import agent_user_name

        pw = pwd.getpwnam(agent_user_name())
    except ImportError, KeyError:
        return
    with contextlib.suppress(OSError):
        os.chmod(path, 0o755)  # nosec B103 — agent must traverse non-secret temp tree
        os.chown(path, pw.pw_uid, pw.pw_gid)


def _git_config(repo_dir: str, key: str, value: str) -> None:
    subprocess.run(
        ["git", "config", "--local", key, value],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )


def _git_get(repo_dir: str, key: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "config", "--get", key],
            cwd=repo_dir,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError, OSError:
        return ""


def write_askpass_script(tmpdir: str, token: str) -> str:
    """Write a GIT_ASKPASS helper returning ``x-access-token`` + the token.

    Git invokes ``GIT_ASKPASS`` twice — once for the username prompt, once for the
    password — passing the prompt text as ``$1``. Returning the token for *both*
    yields ``https://<token>:<token>@github.com``, which GitHub accepts only
    intermittently (token-as-username is not the documented form) and otherwise
    rejects with ``remote: invalid credentials``. Emit the documented pair
    instead: username ``x-access-token``, password ``<token>``.
    """
    path = Path(tmpdir) / "credentials"
    path.mkdir(mode=0o700, exist_ok=True)
    path.chmod(0o700)
    # Parent temp dir may be agent-owned (see ``_prepare_temp_dir_for_agent``);
    # secrets must stay root-only even when the agent can traverse the parent.
    if os.getuid() == 0:
        with contextlib.suppress(OSError):
            os.chown(path, 0, 0)
    askpass = path / "git-askpass.sh"
    askpass.write_text(
        "#!/bin/sh\n"
        "# generated by mergecraft — do not commit\n"
        'case "$1" in\n'
        "  Username*) echo 'x-access-token' ;;\n"
        f'  *) echo "{token}" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    askpass.chmod(0o600)
    if os.getuid() == 0:
        with contextlib.suppress(OSError):
            os.chown(askpass, 0, 0)
    register_created_path(str(askpass))
    return str(askpass)


def setup_git(
    *,
    git_token: str,
    owner: str,
    name: str,
    tool_state: ToolState,
    shell: ShellPerm | ShellPermission = "restricted",
    tmpdir: str | None = None,
    octokit: GitHubClient | None = None,
) -> None:
    """Configure git identity and askpass for the primary working tree."""
    from mergecraft.mcp.tool_state import primary_repo_state, require_repo_state

    repo_dir = os.getcwd()
    try:
        repo_state = require_repo_state(tool_state, owner, name)
    except RuntimeError:
        repo_state = primary_repo_state(tool_state)
    repo_state.dir = repo_dir

    logger.info("» setting up git configuration...")
    current_email = _git_get(repo_dir, "user.email")
    should_set = (
        not current_email or current_email == "github-actions[bot]@users.noreply.github.com"
    )
    if should_set:
        _git_config(repo_dir, "user.email", MERGECRAFT_BOT_EMAIL)
        _git_config(repo_dir, "user.name", MERGECRAFT_BOT_NAME)
        logger.debug("» git user configured (using defaults)")
    else:
        logger.debug("» git user already configured ({}), skipping", current_email)

    # ``shell=enabled`` is the only mode that allows git hooks to run (W3.2).
    if shell != "enabled":
        _git_config(repo_dir, "core.hooksPath", "/dev/null")
        logger.debug("» git hooks disabled (shell={})", shell)

    from mergecraft.utils.workspace import register_workspace_root

    register_workspace_root(repo_dir)

    temp = tmpdir or os.environ.get("MERGECRAFT_TEMP_DIR") or create_temp_directory()
    # Write then immediately shred: retained askpass on disk is residual attack
    # surface for root-UID MCP ``shell=restricted`` (Thermos Final). Auth is
    # brokered per-op via MCP git ``http.extraHeader`` — never ``GIT_ASKPASS``.
    askpass = write_askpass_script(temp, git_token)
    tool_state.git_askpass_path = askpass
    askpass_path = Path(askpass)
    if askpass_path.is_file():
        _secure_overwrite_file(askpass_path)
        with contextlib.suppress(OSError):
            askpass_path.unlink()
    os.environ["GIT_TERMINAL_PROMPT"] = "0"
    push_url = f"https://github.com/{owner}/{name}.git"
    repo_state.push_url = push_url
    logger.info("» git credentials brokered for {}", f"{owner}/{name}")

    _ = octokit  # reserved for future remote probes


def wipe_runner_leak_surface() -> None:
    """Remove only mergeCraft-registered leak-surface paths (W2.4).

    Never deletes the active run temp dir (``MERGECRAFT_TEMP_DIR`` /
    ``_temp_dir``): ``main`` creates that directory before this wipe runs, and
    ``cleanup_temp_directory`` owns its lifecycle. Wiping it here left
    ``setup_git`` / askpass with a missing parent (Action-image E2E / W11).
    """
    preserve: set[str] = set()
    for env_var in (
        "GITHUB_OUTPUT",
        "GITHUB_ENV",
        "GITHUB_PATH",
        "GITHUB_STATE",
        "GITHUB_STEP_SUMMARY",
    ):
        path = os.environ.get(env_var)
        if path:
            try:
                preserve.add(str(Path(path).resolve()))
            except OSError:
                preserve.add(path)

    active_temp = _temp_dir or os.environ.get("MERGECRAFT_TEMP_DIR")
    if active_temp:
        try:
            preserve.add(str(Path(active_temp).resolve()))
        except OSError:
            preserve.add(active_temp)

    wiped: list[str] = []

    def try_unlink(path: Path) -> None:
        try:
            resolved = str(path.resolve())
        except OSError:
            resolved = str(path)
        if resolved in preserve or str(path) in preserve:
            return
        # Also preserve anything nested under the active run temp dir.
        if active_temp:
            try:
                path.resolve().relative_to(Path(active_temp).resolve())
            except ValueError, OSError:
                pass
            else:
                return
        if resolved not in _created_paths and str(path) not in _created_paths:
            return
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                _secure_overwrite_file(path)
                path.unlink(missing_ok=True)
            wiped.append(str(path))
            _created_paths.discard(resolved)
            _created_paths.discard(str(path))
        except OSError:
            pass

    for registered in list(_created_paths):
        try_unlink(Path(registered))

    if wiped:
        logger.info("» wiped {} leak-surface file(s) from $RUNNER_TEMP", len(wiped))


__all__ = [
    "MERGECRAFT_BOT_EMAIL",
    "MERGECRAFT_BOT_NAME",
    "cleanup_temp_directory",
    "create_temp_directory",
    "register_created_path",
    "setup_git",
    "wipe_runner_leak_surface",
    "write_askpass_script",
]
