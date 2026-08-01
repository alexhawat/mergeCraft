"""Codex CLI agent harness — invokes ``codex exec`` with MCP config."""

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
    payload_shell_mode,
)
from mergecraft.agents.verifier import VERIFIER_AGENT_NAME, VERIFIER_SYSTEM_PROMPT
from mergecraft.types import MERGECRAFT_MCP_NAME

CODEX_AUTH_ENV = "CODEX_AUTH_JSON"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"


def _strip_provider_prefix(specifier: str) -> str:
    slash = specifier.find("/")
    return specifier[slash + 1 :] if slash > 0 else specifier


def _codex_home(ctx: AgentRunContext) -> Path:
    return Path(ctx.tmpdir) / ".codex"


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_string_list(values: list[str]) -> str:
    inner = ", ".join(_toml_string(item) for item in values)
    return f"[{inner}]"


def _extract_refresh_token(auth_json: str) -> str | None:
    try:
        data = json.loads(auth_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else data
    if isinstance(tokens, dict):
        refresh = tokens.get("refresh_token") or tokens.get("refresh")
        if isinstance(refresh, str) and refresh:
            return refresh
    refresh = data.get("refresh_token") or data.get("refresh")
    return refresh if isinstance(refresh, str) and refresh else None


def _save_codex_writeback_state(*, auth_path: Path, auth_json: str) -> None:
    refresh = _extract_refresh_token(auth_json)
    if not refresh:
        return
    payload = json.dumps(
        {
            "authPath": str(auth_path),
            "originalRefresh": refresh,
        }
    )
    state_file = os.environ.get("GITHUB_STATE")
    if state_file:
        with open(state_file, "a", encoding="utf-8") as fh:
            fh.write(f"codex_writeback={payload}\n")
    os.environ["STATE_codex_writeback"] = payload  # noqa: SIM112 — matches action/post.py _get_state("codex_writeback")


def _has_openai_api_key() -> bool:
    return bool(os.environ.get(OPENAI_API_KEY_ENV, "").strip())


def _codex_subscription_auth_usable(raw: str) -> bool:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    if _extract_refresh_token(raw):
        return True
    tokens = data.get("tokens")
    if isinstance(tokens, dict):
        for key in ("access_token", "access", "refresh_token", "refresh"):
            val = tokens.get(key)
            if isinstance(val, str) and val.strip():
                return True
    for key in ("access_token", "access"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return True
    return False


def _setup_codex_auth(ctx: AgentRunContext, *, codex_home: Path) -> None:
    raw = os.environ.get(CODEX_AUTH_ENV, "").strip()
    if raw and _codex_subscription_auth_usable(raw):
        codex_home.mkdir(parents=True, exist_ok=True)
        auth_path = codex_home / "auth.json"
        auth_path.write_text(raw, encoding="utf-8")
        _save_codex_writeback_state(auth_path=auth_path, auth_json=raw)
        return
    if raw:
        logger.warning(
            "{} is set but not usable subscription JSON — falling back to {} when present",
            CODEX_AUTH_ENV,
            OPENAI_API_KEY_ENV,
        )
    if _has_openai_api_key():
        logger.info("using {} for Codex CLI authentication", OPENAI_API_KEY_ENV)


def _build_subagent_instructions() -> str:
    return "\n\n".join(
        [
            "Registered read-only subagents (spawn via Codex subagent tooling when needed):",
            f"## {REVIEWER_AGENT_NAME}",
            REVIEWER_SYSTEM_PROMPT,
            f"## {VERIFIER_AGENT_NAME}",
            VERIFIER_SYSTEM_PROMPT,
        ]
    )


def _sandbox_mode(ctx: AgentRunContext) -> str:
    shell = payload_shell_mode(ctx)
    if shell == "enabled":
        return "workspace-write"
    return "read-only"


def write_mcp_config(ctx: AgentRunContext) -> str:
    """Write Codex ``config.toml`` under ``$CODEX_HOME`` and return its path."""
    codex_home = _codex_home(ctx)
    codex_home.mkdir(parents=True, exist_ok=True)
    instructions_parts: list[str] = []
    if ctx.instructions.system:
        instructions_parts.append(ctx.instructions.system)
    instructions_parts.append(_build_subagent_instructions())
    instructions_path = codex_home / "mergecraft-instructions.md"
    instructions_path.write_text("\n\n".join(instructions_parts), encoding="utf-8")

    disabled_tools = [str(name) for name in ctx.subagent_denied_tools]
    sandbox_mode = _sandbox_mode(ctx)
    lines = [
        f"approval_policy = {_toml_string('never' if os.environ.get('CI') == 'true' else 'on-request')}",
        f"sandbox_mode = {_toml_string(sandbox_mode)}",
        f"experimental_instructions_file = {_toml_string(str(instructions_path))}",
        f"model_reasoning_effort = {_toml_string('high')}",
        "",
        f"[mcp_servers.{MERGECRAFT_MCP_NAME}]",
        f"url = {_toml_string(ctx.mcp_server_url)}",
    ]
    if disabled_tools:
        lines.append(f"disabled_tools = {_toml_string_list(disabled_tools)}")
    # mergeCraft PR reviews run with shell disabled → read-only sandbox. Codex still
    # needs localhost HTTP to the mergecraft MCP server (checkout_pr, review submit,
    # CI logs, …). Without network_access the tool set is empty and Codex falls back
    # to requesting its optional GitHub plugin instead.
    if ctx.mcp_server_url:
        if sandbox_mode == "workspace-write":
            lines.extend(
                [
                    "",
                    "[sandbox_workspace_write]",
                    "network_access = true",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "[sandbox_read_only]",
                    "network_access = true",
                ]
            )

    config_path = codex_home / "config.toml"
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(config_path)


async def _install(_token: str | None = None) -> str:
    path = shutil.which("codex")
    if path:
        return path
    local = Path(ctx_tmpdir_fallback()) / "node_modules" / ".bin" / "codex"
    if local.exists():
        return str(local)
    msg = "codex CLI not found on PATH. Install @openai/codex or ensure `codex` is available."
    raise FileNotFoundError(msg)


def ctx_tmpdir_fallback() -> str:
    return os.environ.get("MERGECRAFT_TEMP_DIR") or "/tmp"


def _build_env(ctx: AgentRunContext) -> dict[str, str]:
    env = dict(os.environ)
    codex_home = _codex_home(ctx)
    env["CODEX_HOME"] = str(codex_home)
    _setup_codex_auth(ctx, codex_home=codex_home)
    return env


def _parse_codex_payload(data: dict[str, Any]) -> tuple[str, AgentUsage | None]:
    output = str(data.get("result") or data.get("output") or data.get("message") or "")
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
            agent="codex",
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


def _parse_codex_stdout(stdout: str) -> tuple[str, AgentUsage | None]:
    text = stdout.strip()
    if not text:
        return "", None

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return _parse_codex_payload(data)
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
        if event.get("type") == "message" and isinstance(event.get("content"), str):
            output = str(event["content"])
        parsed_output, parsed_usage = _parse_codex_payload(event)
        if parsed_output:
            output = parsed_output
        if parsed_usage is not None:
            usage = parsed_usage
        if event.get("type") in {"turn.completed", "agent-turn-complete", "result"}:
            break
    return output, usage


def _run_codex_once(
    *,
    cli: str,
    prompt: str,
    ctx: AgentRunContext,
    mcp_config: str,
    continue_session: bool = False,
) -> AgentResult:
    del mcp_config  # config lives in $CODEX_HOME/config.toml written by write_mcp_config()
    model = None
    if ctx.resolved_model:
        model = _strip_provider_prefix(ctx.resolved_model)

    cmd = [
        cli,
        "exec",
        "--json",
    ]
    if model:
        cmd.extend(["--model", model])
    cmd.extend(["--sandbox", _sandbox_mode(ctx)])
    if continue_session:
        cmd.extend(["resume", "--last"])
    cmd.append(prompt or ctx.instructions.user)

    logger.info("invoking codex CLI (model={})", model or "default")
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
        return AgentResult(success=False, error="codex CLI timed out")

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if stderr.strip():
        for line in stderr.strip().splitlines()[-20:]:
            logger.debug("[codex] {}", line)

    output, usage = _parse_codex_stdout(stdout)

    if completed.returncode != 0:
        return AgentResult(
            success=False,
            output=output or None,
            error=stderr.strip() or f"codex exited {completed.returncode}",
            usage=usage,
        )
    return AgentResult(success=True, output=output or None, usage=usage)


async def _run(ctx: AgentRunContext) -> AgentResult:
    try:
        cli = await _install(None)
    except FileNotFoundError as err:
        return AgentResult(success=False, error=str(err))

    mcp_config = write_mcp_config(ctx)
    initial = _run_codex_once(
        cli=cli,
        prompt=ctx.instructions.user,
        ctx=ctx,
        mcp_config=mcp_config,
    )

    async def resume(prompt: str) -> AgentResult:
        return _run_codex_once(
            cli=cli,
            prompt=prompt,
            ctx=ctx,
            mcp_config=mcp_config,
            continue_session=True,
        )

    result = await run_post_run_retry_loop(ctx, initial=initial, resume=resume)
    return await finalize_agent_result(ctx, result)


codex = agent(name="codex", install=_install, run=_run)
