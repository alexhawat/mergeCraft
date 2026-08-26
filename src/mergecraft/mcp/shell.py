"""Restricted shell + kill_background tools with CI unshare sandboxing.

Timeout/cancel tears down the shell process group via
:func:`mergecraft.utils.process_group.kill_process_group` (``os.killpg``
TERM → grace → KILL), matching agent CLI teardown (W9 / ``#14``).
"""

from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.mcp.shared import ToolClass, execute, tool
from mergecraft.mcp.tool_state import BackgroundProcess, primary_repo_state
from mergecraft.utils.process_group import kill_process_group
from mergecraft.utils.secrets import resolve_env
from mergecraft.utils.workspace import (
    WorkspacePathError,
    allowed_workspace_roots,
    git_repo_root,
    resolve_allowed_working_directory,
)

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

SandboxMethod = Literal["unshare", "sudo-unshare", "none"]
MAX_OUTPUT_CHARS = 5000

_detected_sandbox: SandboxMethod | None = None
_detected_netns: bool | None = None


def _reset_shell_detection_globals() -> None:
    global _detected_sandbox, _detected_netns
    _detected_sandbox = None
    _detected_netns = None


def reset_detection_cache() -> None:
    """Clear cached sandbox / netns probe results (xdist isolation / #421)."""
    _reset_shell_detection_globals()
    from mergecraft.analyzers.sandbox import probe_capabilities

    probe_capabilities.cache_clear()


def get_sandbox_method() -> SandboxMethod:
    return detect_sandbox_method()


def detect_sandbox_method() -> SandboxMethod:
    global _detected_sandbox
    if _detected_sandbox is not None:
        return _detected_sandbox
    from mergecraft.analyzers.sandbox import probe_capabilities

    caps = probe_capabilities()
    if caps.pid_namespace and caps.pid_namespace_method in {"unshare", "sudo-unshare"}:
        _detected_sandbox = caps.pid_namespace_method
        return _detected_sandbox
    _detected_sandbox = "none"
    logger.info("PID namespace isolation not available")
    return "none"


def network_namespace_available() -> bool:
    """True when ``unshare --net`` works in this environment (W12.7 / #35).

    Probed once and cached via :func:`mergecraft.analyzers.sandbox.probe_capabilities`.
    """
    global _detected_netns
    if _detected_netns is not None:
        return _detected_netns
    from mergecraft.analyzers.sandbox import probe_capabilities

    caps = probe_capabilities()
    _detected_netns = caps.network_namespace
    if not _detected_netns:
        logger.debug(
            "network namespace unavailable (unshare --net failed); "
            "MCP shell network stays outside the sandbox guarantee"
        )
    return _detected_netns


# Every construct that opens a fresh command position for the shell: the
# separators (`;`, `&&`, `||`, `|`, newline), command substitution (`$(…)` and
# backticks), and subshell/group openers. The previous class was `[;&|]`, which
# omitted the newline — and `bash -c` runs every line of its argument.
_COMMAND_SEGMENT = re.compile(r"\$\(|[;&|\n\r(){}`]")
# Commands that take another command as their argument, so git can hide behind
# them. `env` and the shells matter most: `env git status` and `sh -c 'git …'`
# both put git at a command position the guard would otherwise not inspect.
_COMMAND_WRAPPERS = frozenset(
    {
        "bash",
        "builtin",
        "chronic",
        "command",
        "dash",
        "doas",
        "env",
        "eval",
        "exec",
        "flock",
        "ionice",
        "ksh",
        "nice",
        "nohup",
        "parallel",
        "proot",
        "script",
        "setsid",
        "sh",
        "ssh-agent",
        "stdbuf",
        "strace",
        "sudo",
        "time",
        "timeout",
        "unbuffer",
        "watch",
        "xargs",
        "zsh",
    }
)
# A wrapper's own path-shaped argument — `flock /tmp/lock git …`,
# `script -q /dev/null git …`. Without this the lock file ends the segment and
# the git that follows is never inspected.
_PATH_ARG = re.compile(r"^/")
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# A wrapper's own numeric argument — `timeout 5 git …`, `nice -n 10 git …`.
# No command name is bare-numeric, so skipping these costs nothing.
_NUMERIC_ARG = re.compile(r"^\d+(?:\.\d+)?[smhd]?$")
# A wrapper flag whose separate operand is a name, not a command — `sudo -u ci
# git status`, `doas -g devs git …`. The user name is neither path-shaped nor
# numeric, so without this it reads as the command word and ends the segment
# before the git behind it is inspected. Glued spellings (`--user=ci`) already
# fall out as flags. The set is not per-wrapper, so the skip yields to a token
# that names git — see the operand branch in ``_is_git_command``.
_WRAPPER_FLAG_TAKES_VALUE = frozenset({"-u", "--user", "-g", "--group"})


def _command_word(token: str) -> str:
    """Strip the quoting and alias-suppressing ``\\`` a shell removes itself.

    A leading backslash only tells the shell "do not expand this as an alias";
    ``\\git`` still runs git. Quotes are stripped for the same reason: the shell
    removes them before resolving the command word.
    """
    return token.strip("\"'").removeprefix("\\")


def _names_git(token: str) -> bool:
    """Whether ``token`` names the git binary under any path spelling."""
    stripped = _command_word(token)
    return bool(stripped) and PurePosixPath(stripped).name == "git"


def _is_git_command(command: str) -> bool:
    """Whether ``command`` invokes git anywhere the shell would run it.

    The shell tool must never run git: the #257 alias/config guard and the path
    confinement live in the dedicated git tools and neither applies to a string
    handed to ``bash -c``, so a single missed spelling reopens the whole
    surface (``git -c alias.z='!sh …' z``, ``git clean``, ``filter-branch``).

    Each command position is scanned past leading environment assignments and
    wrapper commands, then the first real command word decides: git under any
    path spelling is refused, anything else ends that segment. That keeps
    ``grep git README`` and ``ls .git`` running while catching ``env git``,
    ``xargs -n1 git``, ``/usr/bin/git``, ``sudo -u ci git`` and ``$(git …)``.

    Defence in depth, not a shell parser: arbitrarily quoted payloads
    (``sh -c 'g''it'``), variable indirection (``G=git; $G status``) and
    ``printf 'git …' | sh`` are out of reach of any token scan, and no addition
    here changes that. The load-bearing controls are the read-only ``.git`` bind
    (``_git_readonly_bind_mounts``) and git-binary hiding inside the namespace
    (``_git_binary_unavailable_fragment``); the git-tool allowlist is separate.
    This scan only raises the cost of spellings that cost nothing.
    """
    for segment in _COMMAND_SEGMENT.split(command):
        after_wrapper = False
        skip_operand = False
        for token in segment.split():
            if skip_operand:
                skip_operand = False
                # The same letter takes an operand to one wrapper and none to
                # the next — `-u` is the target user to `sudo` but `--ungroup`
                # to `parallel` and `set -u` to `sh`, where the token behind it
                # is the command. Reading a git there costs a false positive on
                # `sudo -u git ls`, which is the cheaper side to be wrong on.
                if not _names_git(token):
                    continue
            if _ENV_ASSIGNMENT.match(token) or _NUMERIC_ARG.match(token) or token.startswith("-"):
                skip_operand = token in _WRAPPER_FLAG_TAKES_VALUE
                continue
            if _names_git(token):
                return True
            word = _command_word(token)
            if PurePosixPath(word).name in _COMMAND_WRAPPERS:
                after_wrapper = True
                continue
            # A wrapper's own operand (`flock /tmp/lock git …`) is not the
            # command word, so it must not end the scan.
            if after_wrapper and _PATH_ARG.match(word):
                continue
            break
    return False


def _cap_output(output: str, tmpdir: str) -> str:
    if len(output) <= MAX_OUTPUT_CHARS:
        return output
    full_path = str(Path(tmpdir) / f"shell-{uuid.uuid4().hex[:8]}.log")
    Path(full_path).write_text(output, encoding="utf-8")
    elided = len(output) - MAX_OUTPUT_CHARS
    return (
        f"... [{elided} chars truncated; full output saved to {full_path}] ...\n"
        f"{output[-MAX_OUTPUT_CHARS:]}"
    )


def _unshare_argv(*, isolate_network: bool) -> list[str]:
    argv = ["unshare", "--pid", "--fork", "--mount-proc"]
    if isolate_network and _network_namespace_available():
        argv.append("--net")
    return argv


def _network_namespace_available() -> bool:
    """Whether ``unshare --net`` works; uses the shared capability probe cache."""
    return network_namespace_available()


def _git_readonly_bind_mounts() -> str:
    """Shell fragment: bind every registered checkout ``.git`` read-only."""
    parts: list[str] = []
    seen: set[str] = set()
    for root in allowed_workspace_roots():
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        escaped = key.replace("'", "'\\''")
        parts.append(
            f"if [ -e '{escaped}/.git' ]; then "
            f"mount --bind '{escaped}/.git' '{escaped}/.git' || exit 1; "
            f"mount -o remount,bind,ro '{escaped}/.git' || exit 1; "
            "fi; "
        )
    if not parts:
        parts.append(
            "for _ws in .; do "
            'if [ -e "$_ws/.git" ]; then '
            'mount --bind "$_ws/.git" "$_ws/.git" || exit 1; '
            'mount -o remount,bind,ro "$_ws/.git" || exit 1; '
            "fi; "
            "done; "
        )
    return "".join(parts)


def _git_binary_unavailable_fragment() -> str:
    """Shell fragment: hide every ``git`` binary from the untrusted namespace."""
    return (
        "while IFS= read -r _g; do "
        'if [ -n "$_g" ] && [ -x "$_g" ]; then mount --bind /dev/null "$_g" || exit 1; fi; '
        "done < <(type -a git 2>/dev/null | awk '{print $NF}' | sort -u); "
        'IFS=: read -ra _path_dirs <<< "${PATH:-}"; '
        'for _dir in "${_path_dirs[@]}"; do '
        'if [ -x "$_dir/git" ]; then mount --bind /dev/null "$_dir/git" || exit 1; fi; '
        "done; "
    )


def _allow_unsandboxed_shell() -> bool:
    return os.environ.get("MERGECRAFT_ALLOW_UNSANDBOXED_SHELL") == "1"


def _spawn_shell(
    command: str,
    *,
    env: dict[str, str],
    cwd: str,
    stdout: Any,
    stderr: Any,
    isolate_network: bool = False,
) -> subprocess.Popen[bytes]:
    method = detect_sandbox_method()
    if isolate_network and not _network_namespace_available():
        msg = (
            "network namespace isolation is required but unavailable "
            "(unshare --net and sudo unshare --net failed)"
        )
        raise RuntimeError(msg)

    fs_mounts = (
        "mkdir -p /var/lib/mergecraft 2>/dev/null; "
        "mount -t tmpfs tmpfs /var/lib/mergecraft 2>/dev/null; "
        f"{_git_readonly_bind_mounts()}"
        f"{_git_binary_unavailable_fragment()}"
    )
    proc_cleanup = (
        "umount /proc 2>/dev/null; umount /proc 2>/dev/null; mount -t proc proc /proc 2>/dev/null;"
    )
    socket_cleanup = " ".join(
        f"mount --bind /dev/null {path} 2>/dev/null;"
        for path in (
            "/var/run/docker.sock",
            "/run/docker.sock",
            "/var/run/podman/podman.sock",
            "/run/podman/podman.sock",
            "/run/containerd/containerd.sock",
            "/var/run/crio/crio.sock",
        )
    )
    wrapped = f"{proc_cleanup} {socket_cleanup} {fs_mounts} {command}"
    unshare_argv = _unshare_argv(isolate_network=isolate_network)

    if method == "unshare":
        return subprocess.Popen(
            [*unshare_argv, "bash", "-c", wrapped],
            cwd=cwd,
            env=env,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
    if method == "sudo-unshare":
        sudo_argv = ["sudo"]
        if env:
            sudo_argv.append(f"--preserve-env={','.join(env)}")
        sudo_argv.extend([*unshare_argv, "bash", "-c", wrapped])
        # env=env: values stay in the Popen environment, not argv (MCB-08 / D9).
        # Do not revert to sudo env KEY=val — that leaks secrets into ps(1).
        return subprocess.Popen(
            sudo_argv,
            cwd=cwd,
            env=env,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
    if not _allow_unsandboxed_shell():
        msg = (
            "pid namespace isolation is unavailable and unsandboxed shell is "
            "refused by default; set MERGECRAFT_ALLOW_UNSANDBOXED_SHELL=1 to override"
        )
        raise RuntimeError(msg)
    # Unsandboxed opt-in: run the command directly — no mount/chmod soup on the host.
    return subprocess.Popen(
        ["bash", "-c", command],
        cwd=cwd,
        env=env,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )


def primary_repo_state_dir_safe(fallback: str) -> str:
    """Best-effort work-tree root for *fallback*, without requiring a ``ctx``."""
    root = git_repo_root(fallback)
    return str(root) if root is not None else fallback


def shell_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        command = str(params["command"])
        if _is_git_command(command):
            msg = (
                "git commands are not allowed in the shell tool. use the dedicated "
                "git tools instead"
            )
            raise RuntimeError(msg)
        timeout_ms = min(int(params.get("timeout") or 30_000), 120_000)
        default_dir = primary_repo_state(ctx.tool_state).dir
        working_directory = params.get("working_directory")
        try:
            cwd = resolve_allowed_working_directory(
                str(working_directory) if working_directory else None,
                default=default_dir,
            )
        except WorkspacePathError as exc:
            raise RuntimeError(str(exc)) from exc
        env = resolve_env("inherit" if ctx.payload.shell == "enabled" else "restricted")
        tmpdir = os.environ.get("MERGECRAFT_TEMP_DIR") or ctx.tmpdir
        # W12.7 — untrusted MCP shell gets ``unshare --net`` when the host
        # supports it; otherwise network stays outside the sandbox guarantee.
        isolate_network = ctx.trust_tier == "untrusted"

        if params.get("background"):
            handle = f"bg-{uuid.uuid4().hex[:8]}"
            output_path = str(Path(tmpdir) / f"{handle}.log")
            pid_path = str(Path(tmpdir) / f"{handle}.pid")
            with open(output_path, "ab") as log_fd:
                proc = _spawn_shell(
                    command,
                    env=env,
                    cwd=cwd,
                    stdout=log_fd,
                    stderr=log_fd,
                    isolate_network=isolate_network,
                )
            if proc.pid is None:
                msg = "failed to start background process"
                raise RuntimeError(msg)
            Path(pid_path).write_text(f"{proc.pid}\n", encoding="utf-8")
            ctx.tool_state.background_processes[handle] = BackgroundProcess(
                pid=proc.pid, output_path=output_path, pid_path=pid_path
            )
            return {
                "handle": handle,
                "outputPath": output_path,
                "pidPath": pid_path,
                "message": f"started background process {handle} (pid {proc.pid})",
            }

        proc = _spawn_shell(
            command,
            env=env,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            isolate_network=isolate_network,
        )
        try:
            stdout_b, stderr_b = proc.communicate(timeout=timeout_ms / 1000)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_process_group(proc.pid)
            stdout_b, stderr_b = proc.communicate(timeout=5)
        stdout = (stdout_b or b"").decode("utf-8", errors="replace")
        stderr = (stderr_b or b"").decode("utf-8", errors="replace")
        output = f"{stdout}\n{stderr}".strip() if stderr else stdout.strip()
        if timed_out:
            output = (
                f"{output}\n[timed out after {timeout_ms}ms]"
                if output
                else f"[timed out after {timeout_ms}ms]"
            )
        exit_code = proc.returncode if proc.returncode is not None else (124 if timed_out else -1)
        return {
            "output": _cap_output(output, tmpdir),
            "exit_code": exit_code,
            "timed_out": timed_out,
        }

    return tool(
        name="shell",
        tool_class=ToolClass.SHELL,
        mutates=True,
        timeout_ms=120_000,
        description=(
            f"Execute shell commands securely. Environment is filtered to remove API "
            f"keys and secrets. Output capped at {MAX_OUTPUT_CHARS} chars. "
            "Do NOT use for git — use dedicated git tools."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "description": {"type": "string"},
                "timeout": {
                    "type": "number",
                    "description": "Timeout in MILLISECONDS. Default 30000, max 120000.",
                },
                "working_directory": {"type": "string"},
                "background": {"type": "boolean"},
            },
            "required": ["command", "description"],
            "additionalProperties": False,
        },
        execute=execute(_run, "shell"),
    )


def kill_background_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        handle = str(params["handle"])
        proc = ctx.tool_state.background_processes.get(handle)
        if proc is None:
            return {
                "success": False,
                "message": f"no background process with handle {handle}",
            }
        kill_process_group(proc.pid)
        ctx.tool_state.background_processes.pop(handle, None)
        return {
            "success": True,
            "message": f"killed background process {handle} (pid {proc.pid})",
        }

    return tool(
        name="kill_background",
        tool_class=ToolClass.SHELL,
        mutates=True,
        description="Kill a background process by its handle.",
        input_schema={
            "type": "object",
            "properties": {"handle": {"type": "string"}},
            "required": ["handle"],
            "additionalProperties": False,
        },
        execute=execute(_run, "kill_background"),
    )
