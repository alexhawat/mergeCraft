"""Agent protocol and shared helpers (ported from agents/shared.ts)."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from mergecraft.mcp.tool_state import ToolState
    from mergecraft.types import AgentId

MAX_STDERR_LINES = 20
MAX_POST_RUN_RETRIES = 3


def spawn_agent_cli(
    cmd: list[str],
    *,
    env: dict[str, str],
    cwd: str | None = None,
) -> subprocess.Popen[str]:
    """Wrap argv with privilege drop and open a session-leader agent process.

    Shared by Claude/Codex/Gemini/OpenCode so wrap + pipes + ``start_new_session``
    stay one place (W9 / Final CQ). Callers own streaming and
    :func:`wait_or_kill_process_group`.

    Wraps argv with :func:`wrap_agent_command` *before* patching ``env`` with
    :func:`agent_subprocess_env` — both resolve the same agent user
    independently and fail closed the same way, but ordering them this way
    means a fail-closed ``setpriv``/user error surfaces at the argv wrap
    (matching every existing test's expectations) rather than only after the
    env has already been rebuilt.
    """
    from mergecraft.utils.privilege import agent_subprocess_env, wrap_agent_command

    wrapped_cmd = wrap_agent_command(cmd)
    resolved_env = agent_subprocess_env(env)

    return subprocess.Popen(
        wrapped_cmd,
        cwd=cwd if cwd is not None else os.getcwd(),
        env=resolved_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        start_new_session=True,
    )


def get_git_status(cwd: str | None = None) -> str:
    try:
        return subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            text=True,
            timeout=10,
        ).strip()
    except Exception:
        return ""


def build_commit_prompt(status: str) -> str:
    return "\n".join(
        [
            "UNCOMMITTED CHANGES — the working tree is dirty. push all changes to a "
            "pull request (new or existing). `git status` must be clean before you finish.",
            "",
            "```",
            status,
            "```",
        ]
    )


@dataclass(slots=True)
class StopHookFailure:
    exit_code: int
    output: str


@dataclass(slots=True)
class SummaryStale:
    file_path: str


@dataclass(slots=True)
class PostRunIssues:
    stop_hook: StopHookFailure | None = None
    dirty_tree: str | None = None
    summary_stale: SummaryStale | None = None
    unsubmitted_review: str | None = None  # "Review" | "IncrementalReview"


def has_post_run_issues(issues: PostRunIssues) -> bool:
    return (
        issues.stop_hook is not None
        or issues.dirty_tree is not None
        or issues.summary_stale is not None
        or issues.unsubmitted_review is not None
    )


@dataclass(slots=True)
class AgentUsage:
    agent: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    cost_usd: float | None = None


@dataclass(slots=True)
class AgentToolUseEvent:
    tool_name: str
    input: Any


@dataclass(slots=True)
class AgentResult:
    success: bool
    output: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    usage: AgentUsage | None = None
    terminal_submission_received: bool = False
    terminal_submission_id: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ResolvedInstructions:
    """Agent prompt bundle — mirrors ``utils.instructions.ResolvedInstructions``."""

    full: str = ""
    system: str = ""
    user: str = ""
    event_instructions: str = ""
    event: str = ""
    runtime: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentRunContext:
    payload: Any
    mcp_server_url: str
    tmpdir: str
    subagent_denied_tools: Sequence[str]
    instructions: Any
    tool_state: ToolState
    api_token: str = ""
    resolved_model: str | None = None
    secret_deny_paths: list[str] | None = None
    todo_tracker: Any = None
    stop_script: str | None = None
    on_activity_timeout: Callable[[], None] | None = None
    on_tool_use: Callable[[AgentToolUseEvent], None] | None = None


def payload_shell_mode(ctx: AgentRunContext) -> str:
    """Read ``shell`` from dict or dataclass payloads (Action uses a dict)."""
    payload = ctx.payload
    shell = payload.get("shell") if isinstance(payload, dict) else getattr(payload, "shell", None)
    return str(shell or "restricted")


def payload_event_branch(ctx: AgentRunContext) -> str | None:
    """Read PR head branch from dict or dataclass event payloads."""
    payload = ctx.payload
    event = payload.get("event") if isinstance(payload, dict) else getattr(payload, "event", None)
    if isinstance(event, dict):
        branch = event.get("branch")
    elif event is not None:
        branch = getattr(event, "branch", None)
    else:
        branch = None
    if isinstance(branch, str) and branch.strip():
        return branch.strip()
    return None


class Agent(Protocol):
    name: AgentId

    async def install(self, token: str | None = None) -> str: ...

    async def run(self, ctx: AgentRunContext) -> AgentResult: ...


@dataclass(slots=True)
class AgentImpl:
    name: AgentId
    _install: Callable[[str | None], Awaitable[str]]
    _run: Callable[[AgentRunContext], Awaitable[AgentResult]]
    _build_env: Callable[[AgentRunContext], dict[str, str]] | None = field(default=None, repr=False)
    _module_file: str | None = field(default=None, repr=False)

    async def install(self, token: str | None = None) -> str:
        return await self._install(token)

    async def run(self, ctx: AgentRunContext) -> AgentResult:
        logger.debug("payload: {}", ctx.payload)
        return await self._run(ctx)

    @property
    def __file__(self) -> str:
        """Source path for AST pins that import AgentImpl via the package export.

        ``from mergecraft.agents import opencode`` resolves to this object, not
        the module — ``tests/security/test_credentials.py`` reads ``.__file__``
        to AST-parse the real opencode driver. Not dead magic.
        """
        if self._module_file is None:
            msg = "no source module registered for this agent"
            raise AttributeError(msg)
        return self._module_file


def agent(
    *,
    name: AgentId,
    install: Callable[[str | None], Awaitable[str]],
    run: Callable[[AgentRunContext], Awaitable[AgentResult]],
    build_env: Callable[[AgentRunContext], dict[str, str]] | None = None,
    module_file: str | None = None,
) -> AgentImpl:
    return AgentImpl(
        name=name,
        _install=install,
        _run=run,
        _build_env=build_env,
        _module_file=module_file,
    )


def format_cost_usd(cost_usd: float) -> str:
    return f"{cost_usd:.4f}"


def merge_agent_usage(a: AgentUsage | None, b: AgentUsage | None) -> AgentUsage | None:
    if a is None and b is None:
        return None
    if a is None:
        assert b is not None
        return AgentUsage(
            agent=b.agent,
            input_tokens=b.input_tokens,
            output_tokens=b.output_tokens,
            cache_read_tokens=b.cache_read_tokens,
            cache_write_tokens=b.cache_write_tokens,
            cost_usd=b.cost_usd,
        )
    if b is None:
        return AgentUsage(
            agent=a.agent,
            input_tokens=a.input_tokens,
            output_tokens=a.output_tokens,
            cache_read_tokens=a.cache_read_tokens,
            cache_write_tokens=a.cache_write_tokens,
            cost_usd=a.cost_usd,
        )
    cache_read = (a.cache_read_tokens or 0) + (b.cache_read_tokens or 0)
    cache_write = (a.cache_write_tokens or 0) + (b.cache_write_tokens or 0)
    cost = (a.cost_usd or 0) + (b.cost_usd or 0)
    return AgentUsage(
        agent=a.agent,
        input_tokens=a.input_tokens + b.input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
        cache_read_tokens=cache_read or None,
        cache_write_tokens=cache_write or None,
        cost_usd=cost or None,
    )


def log_token_table(
    *,
    input_tokens: int,
    cache_read: int,
    cache_write: int,
    output: int,
    cost_usd: float | None = None,
) -> None:
    total = input_tokens + cache_read + cache_write + output
    row = (
        f"Input={input_tokens} CacheRead={cache_read} CacheWrite={cache_write} "
        f"Output={output} Total={total}"
    )
    if cost_usd is not None and cost_usd > 0:
        row += f" Cost($)={format_cost_usd(cost_usd)}"
    logger.info("token usage: {}", row)


def wrap_agent_subprocess(cmd: list[str]) -> list[str]:
    """Prefix argv with ``setpriv`` so agent CLIs run as the ``mergecraft`` user (W3.4).

    Back-compat alias for :func:`mergecraft.utils.privilege.wrap_agent_command`.
    Agent spawn sites import ``wrap_agent_command`` directly; this name remains
    for tests and any external callers that still use the agents-package facade.
    """
    from mergecraft.utils.privilege import wrap_agent_command

    return wrap_agent_command(cmd)
