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
from mergecraft.utils.workspace import WorkspacePathError, resolve_allowed_working_directory

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

SandboxMethod = Literal["unshare", "sudo-unshare", "none"]
MAX_OUTPUT_CHARS = 5000

_detected_sandbox: SandboxMethod | None = None
_detected_netns: bool | None = None


def get_sandbox_method() -> SandboxMethod:
    return detect_sandbox_method()


def detect_sandbox_method() -> SandboxMethod:
    global _detected_sandbox
    if _detected_sandbox is not None:
        return _detected_sandbox
    if os.environ.get("CI") != "true":
        _detected_sandbox = "none"
        logger.debug("sandbox disabled (CI !== true)")
        return "none"
    try:
        result = subprocess.run(
            ["unshare", "--pid", "--fork", "--mount-proc", "true"],
            timeout=5,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            _detected_sandbox = "unshare"
            return "unshare"
    except Exception as exc:
        logger.warning("unshare probe failed: {}", exc)
    try:
        result = subprocess.run(
            ["sudo", "unshare", "--pid", "--fork", "--mount-proc", "true"],
            timeout=5,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            _detected_sandbox = "sudo-unshare"
            return "sudo-unshare"
    except Exception as exc:
        logger.warning("sudo-unshare probe failed: {}", exc)
    _detected_sandbox = "none"
    logger.info("PID namespace isolation not available")
    return "none"


def network_namespace_available() -> bool:
    """True when ``unshare --net`` works in this environment (W12.7 / #35).

    Probed once and cached. Outside CI the probe is skipped (same policy as
    PID namespaces) — callers treat that as unavailable and lean on credential
    isolation instead.
    """
    global _detected_netns
    if _detected_netns is not None:
        return _detected_netns
    if os.environ.get("CI") != "true":
        _detected_netns = False
        return False
    try:
        result = subprocess.run(
            ["unshare", "--net", "true"],
            timeout=5,
            capture_output=True,
            check=False,
        )
        _detected_netns = result.returncode == 0
    except OSError:
        _detected_netns = False
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
        "command",
        "dash",
        "doas",
        "env",
        "eval",
        "exec",
        "ksh",
        "nice",
        "nohup",
        "setsid",
        "sh",
        "stdbuf",
        "sudo",
        "time",
        "timeout",
        "xargs",
        "zsh",
    }
)
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# A wrapper's own numeric argument — `timeout 5 git …`, `nice -n 10 git …`.
# No command name is bare-numeric, so skipping these costs nothing.
_NUMERIC_ARG = re.compile(r"^\d+(?:\.\d+)?[smhd]?$")


def _names_git(token: str) -> bool:
    """Whether ``token`` names the git binary under any path spelling."""
    stripped = token.strip("\"'")
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
    ``xargs -n1 git``, ``/usr/bin/git`` and ``$(git …)``.

    Defence in depth, not a shell parser: arbitrarily quoted payloads
    (``sh -c 'g''it'``) are out of reach of any token scan. The tool allowlist
    in the git tools remains the primary control.
    """
    for segment in _COMMAND_SEGMENT.split(command):
        for token in segment.split():
            if _ENV_ASSIGNMENT.match(token) or _NUMERIC_ARG.match(token) or token.startswith("-"):
                continue
            if _names_git(token):
                return True
            if token.strip("\"'") in _COMMAND_WRAPPERS:
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
    if isolate_network and network_namespace_available():
        argv.append("--net")
    return argv


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
    if os.environ.get("CI") == "true" and method == "none":
        msg = (
            "pid namespace isolation is required in CI but unavailable "
            "(both unshare and sudo unshare failed)"
        )
        raise RuntimeError(msg)

    repo_root = os.environ.get("GITHUB_WORKSPACE") or primary_repo_state_dir_safe(cwd)
    escaped = repo_root.replace("'", "'\\''")
    fs_mounts = (
        "mkdir -p /var/lib/mergecraft 2>/dev/null; "
        "mount -t tmpfs tmpfs /var/lib/mergecraft 2>/dev/null; "
        f"[ -e '{escaped}/.git' ] && mount --bind '{escaped}/.git' '{escaped}/.git' "
        f"2>/dev/null && mount -o remount,bind,ro '{escaped}/.git' 2>/dev/null; "
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
        return subprocess.Popen(
            [
                "sudo",
                "env",
                *[f"{k}={v}" for k, v in env.items()],
                *unshare_argv,
                "bash",
                "-c",
                wrapped,
            ],
            cwd=cwd,
            env={},
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
    return subprocess.Popen(
        ["bash", "-c", command],
        cwd=cwd,
        env=env,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )


def primary_repo_state_dir_safe(fallback: str) -> str:
    try:
        # best-effort without requiring ctx
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=fallback,
            text=True,
            timeout=5,
        )
        return out.strip() or fallback
    except Exception:
        return fallback


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
