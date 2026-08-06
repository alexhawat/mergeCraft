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
CODEX_REVIEW_PERMISSION_PROFILE = "mergecraft-review"

# Mirrors mergecraft.utils.git_setup — Codex refuses PATH aliases under these.
_FORBIDDEN_TEMP_ROOTS = ("/tmp", "/private/tmp", "/var/tmp", "/usr/tmp")


def _strip_provider_prefix(specifier: str) -> str:
    slash = specifier.find("/")
    return specifier[slash + 1 :] if slash > 0 else specifier


def _is_under_forbidden_temp(path: Path) -> bool:
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


def _safe_codex_home_parent(ctx: AgentRunContext) -> Path:
    """Parent for ``CODEX_HOME`` that Codex will accept for PATH aliases."""
    tmp = Path(ctx.tmpdir)
    if not _is_under_forbidden_temp(tmp):
        return tmp
    for key in ("MERGECRAFT_CODEX_HOME_PARENT", "RUNNER_TEMP", "GITHUB_WORKSPACE"):
        raw = os.environ.get(key, "").strip()
        if not raw:
            continue
        candidate = Path(raw)
        if _is_under_forbidden_temp(candidate):
            continue
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        return candidate / tmp.name
    cache = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "mergecraft"
    cache.mkdir(parents=True, exist_ok=True)
    return cache / tmp.name


def _codex_home(ctx: AgentRunContext) -> Path:
    """Return ``$CODEX_HOME`` for this run.

    Codex 0.14x refuses to install PATH-alias helper binaries when home is under
    ``/tmp`` (world-writable temp). Prefer the run tmpdir when it is safe;
    otherwise relocate under ``RUNNER_TEMP`` / workspace / cache.
    """
    return _safe_codex_home_parent(ctx) / ".codex"


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


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


def _codex_mcp_tool_preamble() -> str:
    """Steer Codex away from the interactive GitHub *plugin* install path.

    Codex 0.14x treats a bare ``checkout_pr`` mention as a request for the
    optional GitHub plugin. That plugin is not installed in the Action image,
    so the agent aborts and mergeCraft posts ``mergecraft-approval: neutral``
    (issue #40). Tools already live on the localhost ``mergecraft`` MCP server
    and are presented as ``mergecraft_<tool>``.
    """
    return (
        "## mergeCraft MCP tools (Codex)\n\n"
        "GitHub/PR operations use the localhost **mergecraft** MCP server "
        f"(config key `[mcp_servers.{MERGECRAFT_MCP_NAME}]`). Tool names are "
        f"prefixed: e.g. `{MERGECRAFT_MCP_NAME}_checkout_pr`, "
        f"`{MERGECRAFT_MCP_NAME}_create_pull_request_review`, "
        f"`{MERGECRAFT_MCP_NAME}_get_check_suite_logs`.\n\n"
        "Do **not** install, request, enable, or wait for any GitHub plugin / "
        "GitHub integration — those are unrelated to mergeCraft and will never "
        "become available in this non-interactive CI session. If a user prompt "
        "says bare `checkout_pr`, call "
        f"`{MERGECRAFT_MCP_NAME}_checkout_pr` instead."
    )


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


def _codex_use_permission_profiles(ctx: AgentRunContext) -> bool:
    """Return True when Codex must use permission profiles for MCP network access.

    Codex legacy ``sandbox_mode = "read-only"`` has no network knob — only
    ``[sandbox_workspace_write].network_access`` exists, and it is ignored in
    read-only mode. Passing ``--sandbox read-only`` forces that legacy path, so
    read-only PR reviews with a localhost mergecraft MCP must use permission
    profiles instead.
    """
    return bool(ctx.mcp_server_url) and _sandbox_mode(ctx) == "read-only"


def _append_mcp_server_lines(lines: list[str], ctx: AgentRunContext) -> None:
    lines.extend(
        [
            "",
            f"[mcp_servers.{MERGECRAFT_MCP_NAME}]",
            f"url = {_toml_string(ctx.mcp_server_url)}",
            # Without this, every tool call is auto-cancelled in CI. Codex
            # auto-approves an MCP call only when the permission profile grants
            # full disk write access (codex_mcp::mcp_permission_prompt_is_auto_approved),
            # and the read-only review profile does not. `approval_policy =
            # "never"` then means the elicitation is never answered, so the call
            # resolves to "user cancelled MCP tool call" — with no interactive
            # user anywhere in the pipeline. The server is ours and the action
            # already runs with push/shell disabled, so approving its tools up
            # front is the intended posture.
            'default_tools_approval_mode = "approve"',
        ]
    )
    # Do NOT put ctx.subagent_denied_tools into ``disabled_tools``. That list is
    # every mutates=True MCP tool (checkout_pr, create_pull_request_review, …)
    # and exists to keep *subagents* read-only. Wiring it onto the main session's
    # MCP server hides those tools from the reviewer itself, so Codex can inspect
    # a PR but can never check it out or submit a review — mergecraft-approval
    # stays neutral forever. Subagent read-only posture stays in the instructions
    # preamble (_build_subagent_instructions); Claude's harness never disabled
    # these tools for the primary agent either.


def _append_read_only_mcp_network_lines(lines: list[str]) -> None:
    profile = CODEX_REVIEW_PERMISSION_PROFILE
    lines.extend(
        [
            "",
            f"default_permissions = {_toml_string(profile)}",
            "",
            f"[permissions.{profile}]",
            'extends = ":read-only"',
            "",
            f"[permissions.{profile}.network]",
            "enabled = true",
            "allow_local_binding = true",
            "",
            f"[permissions.{profile}.network.domains]",
            '"api.openai.com" = "allow"',
            '"*.openai.com" = "allow"',
            '"127.0.0.1" = "allow"',
            '"localhost" = "allow"',
        ]
    )


def write_mcp_config(ctx: AgentRunContext) -> str:
    """Write Codex ``config.toml`` under ``$CODEX_HOME`` and return its path."""
    codex_home = _codex_home(ctx)
    codex_home.mkdir(parents=True, exist_ok=True)
    instructions_parts: list[str] = []
    if ctx.mcp_server_url:
        instructions_parts.append(_codex_mcp_tool_preamble())
    if ctx.instructions.system:
        instructions_parts.append(ctx.instructions.system)
    instructions_parts.append(_build_subagent_instructions())
    instructions_path = codex_home / "mergecraft-instructions.md"
    instructions_path.write_text("\n\n".join(instructions_parts), encoding="utf-8")

    sandbox_mode = _sandbox_mode(ctx)
    use_permission_profiles = _codex_use_permission_profiles(ctx)
    lines = [
        f"approval_policy = {_toml_string('never' if os.environ.get('CI') == 'true' else 'on-request')}",
        f"experimental_instructions_file = {_toml_string(str(instructions_path))}",
        f"model_reasoning_effort = {_toml_string('high')}",
    ]
    if use_permission_profiles:
        _append_read_only_mcp_network_lines(lines)
    else:
        lines.append(f"sandbox_mode = {_toml_string(sandbox_mode)}")
        if ctx.mcp_server_url and sandbox_mode == "workspace-write":
            lines.extend(
                [
                    "",
                    "[sandbox_workspace_write]",
                    "network_access = true",
                ]
            )

    if ctx.mcp_server_url:
        _append_mcp_server_lines(lines, ctx)

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
    # Legacy ``--sandbox read-only`` cannot reach localhost MCP; permission profiles
    # in config.toml own sandbox/network policy for that case.
    if not _codex_use_permission_profiles(ctx):
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
