"""Gemini CLI agent harness — invokes ``gemini`` with MCP settings."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

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

GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
GOOGLE_GENERATIVE_AI_API_KEY_ENV = "GOOGLE_GENERATIVE_AI_API_KEY"


def _strip_provider_prefix(specifier: str) -> str:
    slash = specifier.find("/")
    return specifier[slash + 1 :] if slash > 0 else specifier


def _gemini_home(ctx: AgentRunContext) -> Path:
    return Path(ctx.tmpdir) / ".gemini"


def _build_subagent_instructions() -> str:
    return "\n\n".join(
        [
            "Registered read-only subagents (spawn when needed):",
            f"## {REVIEWER_AGENT_NAME}",
            REVIEWER_SYSTEM_PROMPT,
            f"## {VERIFIER_AGENT_NAME}",
            VERIFIER_SYSTEM_PROMPT,
        ]
    )


def write_mcp_config(ctx: AgentRunContext) -> str:
    """Write Gemini ``settings.json`` under the run temp dir and return its path."""
    gemini_home = _gemini_home(ctx)
    gemini_home.mkdir(parents=True, exist_ok=True)
    instructions_parts: list[str] = []
    if ctx.instructions.system:
        instructions_parts.append(ctx.instructions.system)
    instructions_parts.append(_build_subagent_instructions())
    instructions_path = gemini_home / "mergecraft-instructions.md"
    instructions_path.write_text("\n\n".join(instructions_parts), encoding="utf-8")

    settings = {
        "mcpServers": {
            MERGECRAFT_MCP_NAME: {
                "httpUrl": ctx.mcp_server_url,
                "trust": True,
            }
        },
        "contextFileName": str(instructions_path.name),
    }
    config_path = gemini_home / "settings.json"
    config_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return str(config_path)


async def _install(_token: str | None = None) -> str:
    path = shutil.which("gemini")
    if path:
        return path
    local = Path(ctx_tmpdir_fallback()) / "node_modules" / ".bin" / "gemini"
    if local.exists():
        return str(local)
    msg = (
        "gemini CLI not found on PATH. Install @google/gemini-cli or ensure `gemini` is available."
    )
    raise FileNotFoundError(msg)


def ctx_tmpdir_fallback() -> str:
    return os.environ.get("MERGECRAFT_TEMP_DIR") or "/tmp"


def _normalize_gemini_api_key(env: dict[str, str]) -> None:
    if env.get(GEMINI_API_KEY_ENV, "").strip():
        return
    alt = env.get(GOOGLE_GENERATIVE_AI_API_KEY_ENV, "").strip()
    if alt:
        env[GEMINI_API_KEY_ENV] = alt


def _build_env(ctx: AgentRunContext) -> dict[str, str]:
    env = dict(os.environ)
    _normalize_gemini_api_key(env)
    # Isolate Gemini user config to the run temp dir (~/.gemini/settings.json).
    env["HOME"] = str(Path(ctx.tmpdir))
    return env


def _parse_gemini_payload(data: dict[str, Any]) -> tuple[str, AgentUsage | None]:
    output = str(data.get("result") or data.get("output") or data.get("response") or "")
    usage_raw = data.get("usage") or {}
    usage: AgentUsage | None = None
    if usage_raw or data.get("total_cost_usd") is not None:
        input_tokens = int(usage_raw.get("input_tokens") or usage_raw.get("inputTokens") or 0)
        output_tokens = int(usage_raw.get("output_tokens") or usage_raw.get("outputTokens") or 0)
        cache_read = int(
            usage_raw.get("cache_read_input_tokens") or usage_raw.get("cacheReadTokens") or 0
        )
        cache_write = int(
            usage_raw.get("cache_creation_input_tokens") or usage_raw.get("cacheWriteTokens") or 0
        )
        cost = data.get("total_cost_usd")
        usage = AgentUsage(
            agent="gemini",
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
    return output, usage


def _parse_gemini_stdout(stdout: str) -> tuple[str, AgentUsage | None]:
    text = stdout.strip()
    if not text:
        return "", None

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return _parse_gemini_payload(data)
    except json.JSONDecodeError:
        pass

    usage: AgentUsage | None = None
    output = text
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        parsed_output, parsed_usage = _parse_gemini_payload(event)
        if parsed_output:
            output = parsed_output
        if parsed_usage is not None:
            usage = parsed_usage
        if event.get("type") in {"result", "turn.completed", "agent-turn-complete"}:
            break
    return output, usage


def _run_gemini_once(
    *,
    cli: str,
    prompt: str,
    ctx: AgentRunContext,
    mcp_config: str,
    continue_session: bool = False,
) -> AgentResult:
    del mcp_config  # MCP lives in $HOME/.gemini/settings.json from write_mcp_config()
    model = None
    if ctx.resolved_model:
        model = _strip_provider_prefix(ctx.resolved_model)

    user_prompt = prompt or ctx.instructions.user
    cmd = [
        cli,
        "-p",
        user_prompt,
        "--output-format",
        "json",
    ]
    if model:
        cmd.extend(["-m", model])
    if continue_session:
        cmd.extend(["--resume", "latest"])
    if os.environ.get("CI") == "true":
        cmd.append("-y")

    logger.info("invoking gemini CLI (model={})", model or "default")
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
        return AgentResult(success=False, error="gemini CLI timed out")

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if stderr.strip():
        for line in stderr.strip().splitlines()[-20:]:
            logger.debug("[gemini] {}", line)

    output, usage = _parse_gemini_stdout(stdout)

    if completed.returncode != 0:
        return AgentResult(
            success=False,
            output=output or None,
            error=stderr.strip() or f"gemini exited {completed.returncode}",
            usage=usage,
        )
    return AgentResult(success=True, output=output or None, usage=usage)


async def _run(ctx: AgentRunContext) -> AgentResult:
    try:
        cli = await _install(None)
    except FileNotFoundError as err:
        return AgentResult(success=False, error=str(err))

    write_mcp_config(ctx)
    initial = _run_gemini_once(
        cli=cli,
        prompt=ctx.instructions.user,
        ctx=ctx,
        mcp_config="",
    )

    async def resume(prompt: str) -> AgentResult:
        return _run_gemini_once(
            cli=cli,
            prompt=prompt,
            ctx=ctx,
            mcp_config="",
            continue_session=True,
        )

    result = await run_post_run_retry_loop(ctx, initial=initial, resume=resume)
    return await finalize_agent_result(ctx, result)


gemini = agent(name="gemini", install=_install, run=_run)
