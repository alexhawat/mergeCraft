"""Agent protocol and shared helpers (ported from agents/shared.ts)."""

from __future__ import annotations

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

    async def install(self, token: str | None = None) -> str:
        return await self._install(token)

    async def run(self, ctx: AgentRunContext) -> AgentResult:
        logger.debug("payload: {}", ctx.payload)
        return await self._run(ctx)


def agent(
    *,
    name: AgentId,
    install: Callable[[str | None], Awaitable[str]],
    run: Callable[[AgentRunContext], Awaitable[AgentResult]],
) -> AgentImpl:
    return AgentImpl(name=name, _install=install, _run=run)


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
