"""Claude Code agent harness — invokes `claude` CLI with MCP config JSON."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from loguru import logger

from mergecraft.agents.post_run import finalize_agent_result, run_post_run_retry_loop
from mergecraft.agents.reviewer import REVIEWER_AGENT_NAME, REVIEWER_SYSTEM_PROMPT
from mergecraft.agents.shared import (
    AgentResult,
    AgentRunContext,
    AgentUsage,
    agent,
    log_token_table,
)
from mergecraft.agents.verifier import VERIFIER_AGENT_NAME, VERIFIER_SYSTEM_PROMPT
from mergecraft.types import MERGECRAFT_MCP_NAME

CLAUDE_EXEC_TOOLS = ("Bash", "Monitor", "REPL", "Workflow")
CLAUDE_EXEC_TOOL_DENY_RULES = [
    *CLAUDE_EXEC_TOOLS,
    *[f"Agent({t})" for t in CLAUDE_EXEC_TOOLS],
]
CLAUDE_DISALLOWED_TOOLS = ",".join(CLAUDE_EXEC_TOOL_DENY_RULES)


def _strip_provider_prefix(specifier: str) -> str:
    slash = specifier.find("/")
    return specifier[slash + 1 :] if slash > 0 else specifier


def write_mcp_config(ctx: AgentRunContext) -> str:
    config_dir = Path(ctx.tmpdir) / ".claude"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    MERGECRAFT_MCP_NAME: {"type": "http", "url": ctx.mcp_server_url},
                }
            }
        ),
        encoding="utf-8",
    )
    return str(config_path)


def build_agents_json() -> str:
    agents = {
        REVIEWER_AGENT_NAME: {
            "description": (
                "Read-only review subagent for lens-based code review. "
                "Reads only — no writes, no state-changing shell or MCP calls."
            ),
            "prompt": REVIEWER_SYSTEM_PROMPT,
            "model": "claude-sonnet-5",
        },
        VERIFIER_AGENT_NAME: {
            "description": (
                "Read-only verification subagent for Critical/Major analyzer findings. "
                "Confirms, downgrades, or drops before publication."
            ),
            "prompt": VERIFIER_SYSTEM_PROMPT,
            "model": "claude-sonnet-5",
        },
    }
    return json.dumps(agents)


async def _install(_token: str | None = None) -> str:
    path = shutil.which("claude")
    if path:
        return path
    # Prefer locally installed package binary if present
    local = Path(ctx_tmpdir_fallback()) / "node_modules" / ".bin" / "claude"
    if local.exists():
        return str(local)
    msg = (
        "claude CLI not found on PATH. Install @anthropic-ai/claude-code "
        "or ensure `claude` is available."
    )
    raise FileNotFoundError(msg)


def ctx_tmpdir_fallback() -> str:
    return os.environ.get("MERGECRAFT_TEMP_DIR") or "/tmp"


_STDERR_TAIL_LINES = 20


def _claude_attempt_context(*, model: str | None, skip_permissions: bool) -> str:
    parts = [f"model={model or 'default'}"]
    if skip_permissions:
        parts.append("--dangerously-skip-permissions")
    if os.environ.get("CI") == "true":
        parts.append("CI=true")
    return ", ".join(parts)


def _build_claude_failure_error(
    *,
    returncode: int,
    stderr: str,
    model: str | None,
    skip_permissions: bool,
) -> str:
    context = _claude_attempt_context(model=model, skip_permissions=skip_permissions)
    stderr_lines = [line for line in (stderr or "").strip().splitlines() if line.strip()]
    if stderr_lines:
        tail = stderr_lines[-_STDERR_TAIL_LINES:]
        stderr_part = "; stderr tail: " + " | ".join(tail)
    else:
        stderr_part = " (no stderr output)"
    return f"claude exited {returncode} ({context}){stderr_part}"


def _build_env(ctx: AgentRunContext) -> dict[str, str]:
    env = dict(os.environ)
    # Agent process keeps full env (needs LLM keys). Secrets are filtered at MCP shell.
    env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
    if ctx.resolved_model:
        # Bedrock / Vertex routing via env when configured upstream
        model = ctx.resolved_model.lower()
        if "bedrock" in model or os.environ.get("CLAUDE_CODE_USE_BEDROCK"):
            env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        if "vertex" in model or os.environ.get("CLAUDE_CODE_USE_VERTEX"):
            env["CLAUDE_CODE_USE_VERTEX"] = "1"
    return env


def _run_claude_once(
    *,
    cli: str,
    prompt: str,
    ctx: AgentRunContext,
    mcp_config: str,
    continue_session: bool = False,
) -> AgentResult:
    model = None
    if ctx.resolved_model:
        model = _strip_provider_prefix(ctx.resolved_model)
    cmd = [
        cli,
        "--print",
        "--output-format",
        "json",
        "--mcp-config",
        mcp_config,
        "--disallowedTools",
        CLAUDE_DISALLOWED_TOOLS,
        "--agents",
        build_agents_json(),
        "--effort",
        "high",
    ]
    if model:
        cmd.extend(["--model", model])
    if continue_session:
        cmd.append("--continue")
    # Permission mode: skip interactive prompts in CI
    skip_permissions = os.environ.get("CI") == "true"
    if skip_permissions:
        cmd.append("--dangerously-skip-permissions")

    system = ctx.instructions.system
    user_prompt = prompt or ctx.instructions.user
    if system:
        cmd.extend(["--system-prompt", system])
    cmd.append(user_prompt)

    logger.info("invoking claude CLI (model={})", model or "default")
    try:
        completed = subprocess.run(
            cmd,
            cwd=os.getcwd(),
            env=_build_env(ctx),
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("MERGECRAFT_AGENT_TIMEOUT", "3600")),
            check=False,
        )
    except FileNotFoundError as err:
        return AgentResult(success=False, error=str(err))
    except subprocess.TimeoutExpired:
        return AgentResult(success=False, error="claude CLI timed out")

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if completed.returncode == 0 and stderr.strip():
        for line in stderr.strip().splitlines()[-_STDERR_TAIL_LINES:]:
            logger.debug("[claude] {}", line)

    usage: AgentUsage | None = None
    output = stdout.strip()
    # Try parse final JSON result event
    try:
        data = json.loads(stdout.strip().splitlines()[-1]) if stdout.strip() else {}
        if isinstance(data, dict):
            output = str(data.get("result") or data.get("output") or output)
            usage_raw = data.get("usage") or {}
            if usage_raw or data.get("total_cost_usd") is not None:
                input_tokens = int(
                    usage_raw.get("input_tokens") or usage_raw.get("inputTokens") or 0
                )
                output_tokens = int(
                    usage_raw.get("output_tokens") or usage_raw.get("outputTokens") or 0
                )
                cache_read = int(
                    usage_raw.get("cache_read_input_tokens")
                    or usage_raw.get("cacheReadTokens")
                    or 0
                )
                cache_write = int(
                    usage_raw.get("cache_creation_input_tokens")
                    or usage_raw.get("cacheWriteTokens")
                    or 0
                )
                cost = data.get("total_cost_usd")
                usage = AgentUsage(
                    agent="claude",
                    input_tokens=input_tokens + cache_read + cache_write,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read or None,
                    cache_write_tokens=cache_write or None,
                    cost_usd=float(cost) if cost is not None else None,
                )
                log_token_table(
                    input_tokens=input_tokens,
                    cache_read=cache_read,
                    cache_write=cache_write,
                    output=output_tokens,
                    cost_usd=usage.cost_usd,
                )
    except json.JSONDecodeError:
        pass

    if completed.returncode != 0:
        context = _claude_attempt_context(model=model, skip_permissions=skip_permissions)
        logger.warning(
            "claude CLI failed (exit={}, {}); stdout={!r}; stderr={!r}",
            completed.returncode,
            context,
            stdout,
            stderr,
        )
        return AgentResult(
            success=False,
            output=output or None,
            error=_build_claude_failure_error(
                returncode=completed.returncode,
                stderr=stderr,
                model=model,
                skip_permissions=skip_permissions,
            ),
            usage=usage,
        )
    return AgentResult(success=True, output=output or None, usage=usage)


async def _run(ctx: AgentRunContext) -> AgentResult:
    try:
        cli = await _install(None)
    except FileNotFoundError as err:
        return AgentResult(success=False, error=str(err))

    mcp_config = write_mcp_config(ctx)
    initial = _run_claude_once(
        cli=cli,
        prompt=ctx.instructions.user,
        ctx=ctx,
        mcp_config=mcp_config,
    )

    async def resume(prompt: str) -> AgentResult:
        return _run_claude_once(
            cli=cli,
            prompt=prompt,
            ctx=ctx,
            mcp_config=mcp_config,
            continue_session=True,
        )

    result = await run_post_run_retry_loop(ctx, initial=initial, resume=resume)
    return await finalize_agent_result(ctx, result)


claude = agent(name="claude", install=_install, run=_run)
