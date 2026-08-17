"""Codex CLI agent harness — invokes ``codex exec`` with MCP config."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.agents.openai_compatible_gateways import (
    CUSTOM_PROVIDER_API_KEY_ENV,
    CUSTOM_PROVIDER_BASE_URL_ENV,
    INDEXED_CUSTOM_PROVIDER_API_KEY_RE,
    INDEXED_CUSTOM_PROVIDER_BASE_URL_RE,
    resolve_gateway_endpoints,
)
from mergecraft.agents.post_run import finalize_agent_result, run_post_run_retry_loop
from mergecraft.agents.reviewer import REVIEWER_AGENT_NAME, REVIEWER_SYSTEM_PROMPT
from mergecraft.agents.shared import (
    AgentResult,
    AgentRunContext,
    AgentUsage,
    agent,
    log_token_table,
    payload_shell_mode,
    spawn_agent_cli,
)
from mergecraft.agents.verifier import VERIFIER_AGENT_NAME, VERIFIER_SYSTEM_PROMPT
from mergecraft.tracing._tool_attrs import (
    emit_verb_subevent,
    enrich_tool_request,
    enrich_tool_response,
)
from mergecraft.tracing.genai import (
    ModelParams,
    output_messages_attrs,
    request_attrs,
    resolve_capture_policy,
    thinking_attrs,
)
from mergecraft.tracing.redaction import redact_tool_payload
from mergecraft.tracing.tracer import (
    ProviderLLMPair,
    _close_provider_llm_pair,
    _open_provider_llm_pair,
)
from mergecraft.types import MERGECRAFT_MCP_NAME
from mergecraft.utils.process_group import track_process_group, wait_or_kill_process_group
from mergecraft.utils.retry_policy import is_retryable_cli_failure
from mergecraft.utils.secrets import build_agent_env

if TYPE_CHECKING:
    from collections.abc import Callable

    from mergecraft.agents._stream_consumer import StreamSpanAccumulator
    from mergecraft.tracing.content import ContentCapture
    from mergecraft.tracing.tracer import Tracer

CODEX_AUTH_ENV = "CODEX_AUTH_JSON"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
CODEX_REVIEW_PERMISSION_PROFILE = "mergecraft-review"
# O4 — the reasoning effort written into ``config.toml`` is the one request
# parameter the codex harness exposes to mergeCraft; the constant keeps the
# TOML value and the span attribute (``mergecraft.reasoning_effort``) from
# drifting apart.
_CODEX_MODEL_REASONING_EFFORT = "high"

# Codex CLI's Linux platform sandbox is bubblewrap + Landlock. Inside a
# container that is *already* namespaced — such as a Docker container action —
# bwrap cannot create a second unprivileged user namespace, and every
# ``codex exec`` dies before doing any work, including a bare ``pwd``. Codex
# recognises these strings for its own probe path but ships no non-interactive
# fallback for a real exec, so mergeCraft has to name the failure itself (#70).
USER_NAMESPACE_FAILURES: tuple[str, ...] = (
    "No permissions to create a new namespace",
    "kernel does not allow non-privileged user namespaces",
    "Failed to create new user namespace",
)

# Operator escape hatch. mergeCraft never selects this on its own: relaxing an
# OS-level sandbox is a judgement about the *environment*, which only the
# workflow author can make. Setting it says "this runner is already an
# ephemeral, isolated container; the nested sandbox is redundant".
CODEX_SANDBOX_ENV = "MERGECRAFT_CODEX_SANDBOX"
CODEX_SANDBOX_UNSANDBOXED = "danger-full-access"


@dataclass(frozen=True, slots=True)
class CodexSubagentDegradation:
    """Declared limitation for Codex subagent dispatch (D15)."""

    kind: str
    toolset_parity: bool


CODEX_SUBAGENT_DEGRADATION = CodexSubagentDegradation(
    kind="prose-only",
    toolset_parity=False,
)

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


def _build_subagent_instructions(subagent_block: str | None = None) -> str:
    if subagent_block is not None:
        return subagent_block
    return "\n\n".join(
        [
            "Registered read-only subagents (spawn via Codex subagent tooling when needed):",
            f"## {REVIEWER_AGENT_NAME}",
            REVIEWER_SYSTEM_PROMPT,
            f"## {VERIFIER_AGENT_NAME}",
            VERIFIER_SYSTEM_PROMPT,
        ]
    )


def _operator_sandbox_override() -> str | None:
    """Return the operator's explicit Codex sandbox choice, if any (#70).

    mergeCraft only honours a value it recognises. An unrecognised value is
    ignored with a warning rather than passed through to the CLI, so a typo
    cannot silently widen or narrow the sandbox.
    """
    raw = os.environ.get(CODEX_SANDBOX_ENV, "").strip().lower()
    if not raw:
        return None
    if raw == CODEX_SANDBOX_UNSANDBOXED:
        return CODEX_SANDBOX_UNSANDBOXED
    logger.warning(
        "ignoring {}={!r}: the only supported value is {!r}",
        CODEX_SANDBOX_ENV,
        raw,
        CODEX_SANDBOX_UNSANDBOXED,
    )
    return None


def _sandbox_is_disabled_by_operator() -> bool:
    """True when the workflow explicitly opted out of Codex's platform sandbox."""
    return _operator_sandbox_override() == CODEX_SANDBOX_UNSANDBOXED


def is_user_namespace_failure(text: str) -> bool:
    """True when CLI output carries bubblewrap's nested-namespace signature (#70)."""
    return any(signature in text for signature in USER_NAMESPACE_FAILURES)


def user_namespace_failure_hint() -> str:
    """Return the actionable remedy for a nested-sandbox failure (#70).

    The failure is environmental, not a reviewer error, and the two are worth
    telling apart: a caller that swallows this with ``continue-on-error`` would
    otherwise see no difference between "this runner cannot sandbox Codex" and
    "the review ran and found nothing".
    """
    return (
        "Codex could not start its Linux platform sandbox: bubblewrap cannot create "
        "a user namespace inside a container that is already namespaced (a Docker "
        "container action, or a runner without unprivileged user namespaces). No "
        "review ran.\n"
        "Remedies:\n"
        f"  - If the runner is already an ephemeral, isolated container, set "
        f"{CODEX_SANDBOX_ENV}={CODEX_SANDBOX_UNSANDBOXED} on the mergeCraft step to "
        "skip Codex's redundant nested sandbox. mergeCraft's own shell/push controls "
        "still apply.\n"
        "  - On a self-hosted runner, enable unprivileged user namespaces "
        "(sysctl kernel.unprivileged_userns_clone=1).\n"
        "  - Or run the review with a provider that does not nest a sandbox."
    )


def _sandbox_mode(ctx: AgentRunContext) -> str:
    if _sandbox_is_disabled_by_operator():
        return CODEX_SANDBOX_UNSANDBOXED
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


def _has_env(name: str) -> bool:
    val = os.environ.get(name)
    return isinstance(val, str) and bool(val.strip())


def _has_any_custom_provider_env() -> bool:
    """True when at least one ``MERGECRAFT_CUSTOM_PROVIDER_*`` env var is set.

    Triggers emission of an empty ``[model_providers]`` table so consumers can
    read it as a dict regardless of whether any pair was complete. The
    contract is that the table's *contents* reflect valid pairs only —
    partial pairs (only one of ``_KEY_<N>`` / ``_URL_<N>``) are dropped.
    """
    for key in os.environ:
        if INDEXED_CUSTOM_PROVIDER_BASE_URL_RE.match(key):
            return True
        if INDEXED_CUSTOM_PROVIDER_API_KEY_RE.match(key):
            return True
        if key in (CUSTOM_PROVIDER_BASE_URL_ENV, CUSTOM_PROVIDER_API_KEY_ENV):
            if _has_env(key):
                return True
    return False


def _append_custom_provider_lines(lines: list[str]) -> None:
    """Emit ``[model_providers.<id>]`` tables for every configured custom provider.

    #71 / W3: routes ``MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}_<N>`` and
    the singleton alias into Codex CLI 0.146's ``model_providers`` config
    schema. Verified against the installed Codex CLI version pinned at
    ``Dockerfile:49`` (``@openai/codex``, locally ``codex-cli 0.146.0``) and
    the upstream ``codex-rs/model-provider-info`` schema: each block carries
    ``base_url``, ``env_key`` (referencing the env-var name, not the resolved
    value — convention 7), and ``wire_api = "responses"`` (the only
    supported wire protocol since February 2026).

    No-op when no ``MERGECRAFT_CUSTOM_PROVIDER_*`` env vars are touched at
    all — the existing ``write_mcp_config`` output is byte-identical to
    today's in that case. Partial pairs (only one half set) emit an empty
    ``model_providers`` table; consumers reading the table find no entries
    and skip.
    """
    if not _has_any_custom_provider_env():
        return
    providers = resolve_gateway_endpoints()
    if not providers:
        # Touched but no valid pair — emit an empty table so readers find a
        # dict. The TOML parser does not care about an empty table.
        lines.append("")
        lines.append("[model_providers]")
        return
    for record in providers.values():
        lines.append("")
        lines.append(f"[model_providers.{record.provider_id}]")
        lines.append(f"name = {_toml_string(record.provider_id)}")
        lines.append(f"base_url = {_toml_string(record.base_url)}")
        lines.append(f"env_key = {_toml_string(record.api_key_env)}")
        lines.append('wire_api = "responses"')


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


def write_mcp_config(
    ctx: AgentRunContext,
    *,
    subagent_block: str | None = None,
) -> str:
    """Write Codex ``config.toml`` under ``$CODEX_HOME`` and return its path."""
    codex_home = _codex_home(ctx)
    codex_home.mkdir(parents=True, exist_ok=True)
    instructions_parts: list[str] = []
    if ctx.mcp_server_url:
        instructions_parts.append(_codex_mcp_tool_preamble())
    if ctx.instructions.system:
        instructions_parts.append(ctx.instructions.system)
    instructions_parts.append(_build_subagent_instructions(subagent_block))
    instructions_path = codex_home / "mergecraft-instructions.md"
    instructions_path.write_text("\n\n".join(instructions_parts), encoding="utf-8")

    sandbox_mode = _sandbox_mode(ctx)
    use_permission_profiles = _codex_use_permission_profiles(ctx)
    lines = [
        f"approval_policy = {_toml_string('never' if os.environ.get('CI') == 'true' else 'on-request')}",
        f"experimental_instructions_file = {_toml_string(str(instructions_path))}",
        f"model_reasoning_effort = {_toml_string(_CODEX_MODEL_REASONING_EFFORT)}",
    ]
    # W3 / #71 — Codex passthrough for OpenAI-compatible providers. No-op
    # when no ``MERGECRAFT_CUSTOM_PROVIDER_*`` env vars are set, so the
    # permission-profile / ``sandbox_mode`` branch below is unchanged
    # when this is a no-op (#70 / D5).
    _append_custom_provider_lines(lines)
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
    codex_home = _codex_home(ctx)
    env = build_agent_env("codex", {"CODEX_HOME": str(codex_home)})
    _setup_codex_auth(ctx, codex_home=codex_home)
    # write_mcp_config() and _setup_codex_auth() both write into $CODEX_HOME
    # (config.toml, mergecraft-instructions.md, auth.json) while this process
    # still runs as root. wrap_agent_command()'s setpriv drops the actual
    # codex subprocess to the unprivileged agent user, but never touches
    # directory ownership — without this, $CODEX_HOME stays root-owned and
    # Codex's own PATH-alias bootstrap (writing under $CODEX_HOME) fails
    # closed with "Permission denied (os error 13)". Chown last, after every
    # root-owned write above has landed.
    from mergecraft.utils.privilege import prepare_workspace_for_agent

    prepare_workspace_for_agent(str(codex_home))
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

    # W6 migration: codex ``--json`` already emits NDJSON events. Switch
    # from ``subprocess.run`` (capture_output=True) to ``subprocess.Popen``
    # and feed the stdout stream through ``consume_stream`` so per-event
    # ``tool.call`` / ``llm.call`` spans are emitted through the W4 tracer.
    # Falls back to the legacy buffered read loop if the streaming Popen
    # path is unavailable (FileNotFoundError — no codex binary on PATH).
    return _run_codex_streaming(
        cmd=cmd,
        ctx=ctx,
        model=model,
    )


def _run_codex_streaming(
    *,
    cmd: list[str],
    ctx: AgentRunContext,
    model: str | None,
) -> AgentResult:
    """Streaming read loop for ``codex exec --json`` (W6).

    The CLI emits a sequence of NDJSON events: ``thread.started``,
    ``item.started`` / ``item.completed`` (with tool calls and tool
    results), ``message.completed`` (assistant text), and
    ``turn.completed`` with the authoritative usage. Each event drives
    a span emission through ``consume_stream``; the resulting
    ``AgentUsage`` matches the legacy last-line parser.
    """
    from mergecraft.agents._stream_consumer import (
        StreamSpanAccumulator,
        consume_stream,
    )
    from mergecraft.tracing.sinks import claim_sink
    from mergecraft.tracing.tracer import (
        Tracer,
        resolve_correlation_from_env,
        resolve_session_id,
    )

    accumulator = StreamSpanAccumulator(agent_name="codex")
    tracer: Tracer | None = None
    try:
        from mergecraft.tracing.resolve import resolve_active_tracing

        sink = claim_sink(resolve_active_tracing())
        if sink is not None:
            correlation = resolve_correlation_from_env()
            session_id = resolve_session_id()
            run_id = str(correlation.get("run_id") or session_id)
            tracer = Tracer(sink=sink, session_id=session_id, run_id=run_id)
    except Exception as exc:
        logger.debug("codex stream tracer resolution failed: {}", exc)

    # OB3 — resolve the content-capture policy only when a tracer is live;
    # the trust tier is ``derive_trust_tier()``'s output carried on the tool
    # state, never an env fallback (D7 — the cap must not be env-defeatable).
    capture_policy = (
        resolve_capture_policy(ctx.tool_state.trust_tier) if tracer is not None else None
    )
    handler, close_all_open_spans = _codex_stream_event_handler(
        tracer=tracer,
        model_id=model or "default",
        capture_policy=capture_policy,
    )

    try:
        process = spawn_agent_cli(cmd, env=_build_env(ctx))
    except FileNotFoundError as err:
        return AgentResult(success=False, error=str(err))

    assert process.stdout is not None
    assert process.stderr is not None

    stderr_text = ""
    returncode: int = -1
    try:
        with track_process_group(process):
            try:
                consume_stream(
                    raw_stream=process.stdout,
                    accumulator=accumulator,
                    handler=handler,
                )
                stderr_text = process.stderr.read() or ""
                returncode = wait_or_kill_process_group(
                    process,
                    timeout=int(os.environ.get("MERGECRAFT_AGENT_TIMEOUT", "3600")),
                )
            except subprocess.TimeoutExpired:
                return AgentResult(success=False, error="codex CLI timed out")
    finally:
        try:
            close_all_open_spans()
        except Exception as exc:
            logger.debug("codex stream handler cleanup failed: {}", exc)

    if stderr_text.strip():
        for line in stderr_text.strip().splitlines()[-20:]:
            logger.debug("[codex] {}", line)

    if accumulator.parsed_event_count > 0:
        output = accumulator.final_output
        usage = accumulator.to_usage()
    else:
        output = None
        usage = None

    if returncode != 0:
        error = stderr_text.strip() or f"codex exited {returncode}"
        # bwrap fails on the very first exec, so this is the difference between
        # "the environment cannot run Codex" and "the reviewer errored" (#70).
        if is_user_namespace_failure(f"{stderr_text}\n{output or ''}"):
            logger.error(
                "codex platform sandbox could not start; no review ran. Set {}={} "
                "if this runner is already an isolated container.",
                CODEX_SANDBOX_ENV,
                CODEX_SANDBOX_UNSANDBOXED,
            )
            error = f"{user_namespace_failure_hint()}\n\ncodex stderr:\n{error}"
        retryable = is_retryable_cli_failure(returncode=returncode, stderr=stderr_text)
        return AgentResult(
            success=False,
            output=output or None,
            error=error,
            usage=usage,
            metadata={"retryable": True} if retryable else {},
        )
    return AgentResult(success=True, output=output or None, usage=usage)


def _sole_open_llm_span(open_pairs: dict[str, ProviderLLMPair | None]) -> Any:
    """Return the llm span of the single open provider pair, else ``None``.

    Codex's ``message.completed`` / reasoning ``item.completed`` events do
    not carry the thread id, so payload attrs can only be stamped when
    exactly one pair is open (the typical shape — one thread per run).
    """
    live = [pair.llm for pair in open_pairs.values() if pair is not None]
    return live[0] if len(live) == 1 else None


def _codex_stream_event_handler(
    *,
    tracer: Tracer | None,
    model_id: str,
    capture_policy: ContentCapture | None = None,
) -> tuple[
    Callable[[StreamSpanAccumulator, dict[str, Any]], None],
    Callable[[], None],
]:
    """Build a ``consume_stream`` handler for codex NDJSON events (W6).

    Codex ``--json`` events:
      - ``thread.started``: open a ``llm.call`` span for the thread.
      - ``item.started`` with ``item.type == "tool_call"``: open a
        ``tool.call`` span keyed on the tool call id.
      - ``item.completed`` with ``item.type == "tool_call"``: stamp
        the tool call's name + input on the open span.
      - ``item.completed`` with ``item.type == "tool_result"``: close
        the matching ``tool.call`` span.
      - ``item.completed`` with ``item.type == "reasoning"``: capture the
        reasoning text on the open ``llm.call`` span (O6/D9, OB3) — gated
        by ``capture_policy``; reasoning inherits the prompt gate.
      - ``message.completed``: surface the assistant text as the
        run's final output; with ``capture_policy`` set, also capture the
        output messages on the open ``llm.call`` span (O5, OB3).
      - ``turn.completed``: replace the accumulator's usage with the
        authoritative final usage and close the thread's ``llm.call``
        span.

    ``capture_policy=None`` (the default) keeps the pre-OB3 attribute
    surface byte-identical: no payload attrs are stamped. The driver
    resolves it via ``resolve_capture_policy(ctx.tool_state.trust_tier)``
    — the ``derive_trust_tier()`` output, never an env fallback (D7).
    """
    # W5 / H1 / M2 — one ``ProviderLLMPair`` per attempt, not two
    # independent dicts keyed by the same id. Opening the provider span and
    # the LLM span is atomic: they share a ``parent_span_id`` and both
    # enter before the first event. The close path is symmetric: the inner
    # ``llm.call`` span closes first (LIFO), then the outer
    # ``provider.call`` span.
    open_tool_spans: dict[str, dict[str, Any]] = {}
    open_pairs: dict[str, ProviderLLMPair | None] = {}
    open_pair_bookkeeping: dict[str, dict[str, Any]] = {}

    def handler(
        accumulator: StreamSpanAccumulator,
        event: dict[str, Any],
    ) -> None:
        event_type = str(event.get("type") or "")

        # Legacy single-blob shape — a final result JSON with no ``type``
        # field (the W6 test suite still pins this contract from the
        # pre-streaming parser). Surface it the same way the legacy
        # ``_parse_codex_payload`` did: ``output`` is ``result`` /
        # ``output`` / ``message``, ``usage`` flows through the accumulator.
        if not event_type:
            output, usage = _parse_codex_payload(event)
            if output:
                accumulator.set_output(output)
            if usage is not None:
                accumulator.replace_usage(
                    {
                        "input_tokens": usage.input_tokens,
                        "output_tokens": usage.output_tokens,
                        "total_cost_usd": usage.cost_usd,
                    }
                )
            return

        if event_type == "thread.started":
            thread_id = str(event.get("thread_id") or "default")
            if thread_id in open_pairs:
                return
            if tracer is not None:
                # T2 / D10 — ``provider.call`` is a real span kind, not an
                # attr. Opens on ``thread.started`` and closes on
                # ``turn.completed``; the ``llm.call`` span becomes its
                # child so Logfire groups every Responses API request under
                # one row with the transport family on it. W5 / H1 — open
                # via the shared pair helper so the provider + llm attrs
                # + ``__enter__`` are applied atomically; the resulting
                # ``ProviderLLMPair`` is the single state unit per attempt.
                pair = _open_provider_llm_pair(
                    tracer,
                    model_id=model_id,
                    family="responses_api",
                    provider_id="openai_codex",
                )
                if pair is not None:
                    # W6 / L3 — ``_open_provider_llm_pair`` already stamps
                    # ``model.id`` on the parent ``provider.call`` span (the
                    # canonical home per the helper docstring). The llm span
                    # inherits the value through the OTel/mergeCraft parent
                    # chain; do not re-stamp here.
                    pair.llm.set_attribute("model.event", "thread.started")
                    pair.llm.set_attribute("gen_ai.system", "openai")
                    pair.llm.set_attribute("gen_ai.operation.name", "chat")
                    pair.llm.set_attribute("gen_ai.request.model", model_id)
                    pair.llm.set_attribute("gen_ai.response.model", model_id)
                    # O4 (OB3) — the one request knob codex exposes: the
                    # reasoning effort mergeCraft itself wrote into
                    # ``config.toml``. No stable OTel name → mergecraft.*.
                    for attr_key, attr_value in request_attrs(
                        model=None,
                        params=ModelParams(reasoning_effort=_CODEX_MODEL_REASONING_EFFORT),
                    ).items():
                        pair.llm.set_attribute(attr_key, attr_value)
                open_pairs[thread_id] = pair
                open_pair_bookkeeping[thread_id] = {"tokens_in": 0, "tokens_out": 0}
            return

        if event_type == "item.started":
            item = event.get("item") or {}
            if not isinstance(item, dict) or item.get("type") != "tool_call":
                return
            tool_id = str(item.get("id") or "")
            tool_name = str(item.get("name") or "unknown")
            if not tool_id:
                return
            if tool_id in open_tool_spans:
                return
            if tracer is not None:
                span = tracer.start_span("tool.call")
                span.__enter__()
                span.set_attribute("tool.name", tool_name)
                span.set_attribute("tool.id", tool_id)
                span.set_attribute("tool.server", "codex")
                span.set_attribute("gen_ai.operation.name", "execute_tool")
                span.set_attribute("gen_ai.tool.name", tool_name)
                span.set_attribute("gen_ai.tool.call.id", tool_id)
                # T1 / D5 / W4 — request-side enrichment is deferred to the
                # ``item.completed`` site because codex's
                # ``item.started`` event does not carry the input payload
                # — codex sends the input on the matching
                # ``item.completed``. The close path below applies
                # ``enrich_tool_request`` + ``enrich_tool_response`` so the
                # byte count + input representation still surface on the
                # span.
                open_tool_spans[tool_id] = {"span": span, "name": tool_name}
            return

        if event_type == "item.completed":
            item = event.get("item") or {}
            if not isinstance(item, dict):
                return
            item_type = item.get("type")
            if item_type == "tool_call":
                tool_id = str(item.get("id") or "")
                entry = open_tool_spans.pop(tool_id, None)
                if entry is None:
                    return
                span_obj = entry.get("span")
                if span_obj is not None:
                    resolved_name = str(item.get("name") or entry.get("name") or "unknown")
                    span_obj.set_attribute("tool.name", resolved_name)
                    span_obj.set_attribute("gen_ai.tool.name", resolved_name)
                    tool_input = str(item.get("input") or "")
                    span_obj.set_attribute("tool.input", tool_input)
                    span_obj.set_attribute("gen_ai.tool.input", redact_tool_payload(tool_input))
                    # T1 / D5 / W4 — request + response enrichment on the
                    # close path. W4 / H2 — the split helpers mean each
                    # call site is one obvious line; the prior codex
                    # double-set bug (``arguments=tool_input,
                    # output=tool_input``) is gone.
                    enrich_tool_request(span_obj, arguments=tool_input)
                    enrich_tool_response(span_obj, output=tool_input)
                    span_obj.close()
                    # T1 / D5 — known-verb tools also emit a verb-specific
                    # child span (tool.browse for ``browser``, etc.) for
                    # finer-grained Logfire grouping. Fire-and-forget; no
                    # new bookkeeping state.
                    emit_verb_subevent(
                        tracer,
                        parent_span_id=span_obj.span_id,
                        tool_name=resolved_name,
                        attrs=dict(span_obj._attrs),
                    )
                return
            if item_type == "tool_result":
                # The matching tool.call span was closed on item.completed
                # above (codex shape). The tool_result just records the
                # output content; nothing to close here.
                return
            if item_type == "reasoning":
                # O6 / D9 (OB3) — codex surfaces reasoning as items; the
                # text goes through the same content gate as prompts.
                if capture_policy is not None:
                    reasoning_text = item.get("text")
                    llm_span = _sole_open_llm_span(open_pairs)
                    if llm_span is not None and isinstance(reasoning_text, str):
                        for attr_key, attr_value in thinking_attrs(
                            reasoning_text, policy=capture_policy
                        ).items():
                            llm_span.set_attribute(attr_key, attr_value)
                return
            return

        if event_type == "message.completed":
            message = event.get("message") or {}
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str) and content:
                accumulator.set_output(content)
                # O5 (OB3) — the assistant text is the completion payload;
                # capture it on the open llm span under the content policy.
                if capture_policy is not None:
                    llm_span = _sole_open_llm_span(open_pairs)
                    if llm_span is not None:
                        for attr_key, attr_value in output_messages_attrs(
                            [{"role": "assistant", "content": content}],
                            policy=capture_policy,
                        ).items():
                            llm_span.set_attribute(attr_key, attr_value)
            return

        if event_type == "turn.completed":
            usage = event.get("usage") if isinstance(event.get("usage"), dict) else None
            if usage is not None:
                accumulator.replace_usage(usage)
            cost = event.get("total_cost_usd")
            if isinstance(cost, (int, float)) and usage is not None:
                accumulator.cost_usd = float(cost)
            # O6 (OB3) — the Responses-API usage shape carries the reasoning
            # token count under output_tokens_details; surface it beside the
            # body metadata. A count is usage metadata, not a body, so it is
            # not gated by the content policy (same as gen_ai.usage.*).
            reasoning_tokens: int | None = None
            if isinstance(usage, dict):
                details = usage.get("output_tokens_details")
                if isinstance(details, dict) and isinstance(
                    details.get("reasoning_tokens"), (int, float)
                ):
                    reasoning_tokens = int(details["reasoning_tokens"])
            # W5 / H1 / M2 — one ``ProviderLLMPair`` per attempt owns the
            # close discipline (inner llm span first, outer provider span
            # second). Stamp the cost + usage attrs on the inner llm span
            # before closing so the per-message totals land on the row.
            for key in list(open_pairs.keys()):
                pair = open_pairs[key]
                bookkeeping = open_pair_bookkeeping.get(key, {})
                if pair is not None:
                    pair.llm.set_attribute("cost.tokens_in", bookkeeping.get("tokens_in", 0))
                    pair.llm.set_attribute("cost.tokens_out", bookkeeping.get("tokens_out", 0))
                    pair.llm.set_attribute(
                        "gen_ai.usage.input_tokens", bookkeeping.get("tokens_in", 0)
                    )
                    pair.llm.set_attribute(
                        "gen_ai.usage.output_tokens", bookkeeping.get("tokens_out", 0)
                    )
                    if reasoning_tokens is not None:
                        pair.llm.set_attribute(
                            "mergecraft.usage.reasoning_tokens", reasoning_tokens
                        )
            for key in list(open_pairs.keys()):
                _close_provider_llm_pair(open_pairs.pop(key))
            open_pair_bookkeeping.clear()
            return

    def close_all() -> None:
        for entry in list(open_tool_spans.values()):
            span_obj = entry.get("span")
            if span_obj is not None:
                span_obj.close()
        open_tool_spans.clear()
        # W5 / H1 / M2 — one ``ProviderLLMPair`` per attempt; the inner
        # ``_close_provider_llm_pair`` enforces the LIFO close discipline.
        for key in list(reversed(list(open_pairs.keys()))):
            _close_provider_llm_pair(open_pairs.pop(key))
        open_pair_bookkeeping.clear()

    return handler, close_all


async def _run(ctx: AgentRunContext) -> AgentResult:
    from mergecraft.agents.harness_render import merge_manifest_metadata, render_for_run

    try:
        cli = await _install(None)
    except FileNotFoundError as err:
        return AgentResult(success=False, error=str(err))

    render_result = render_for_run(ctx, "codex")
    subagent_block = render_result.payload if isinstance(render_result.payload, str) else None
    mcp_config = write_mcp_config(ctx, subagent_block=subagent_block)
    # Blocking Popen/wait/stream consume runs in a worker thread so
    # ``asyncio.wait_for`` in ``main`` can preempt the coroutine (W9.2).
    initial = await asyncio.to_thread(
        _run_codex_once,
        cli=cli,
        prompt=ctx.instructions.user,
        ctx=ctx,
        mcp_config=mcp_config,
    )

    async def resume(prompt: str) -> AgentResult:
        return await asyncio.to_thread(
            _run_codex_once,
            cli=cli,
            prompt=prompt,
            ctx=ctx,
            mcp_config=mcp_config,
            continue_session=True,
        )

    result = await run_post_run_retry_loop(ctx, initial=initial, resume=resume)
    finalized = await finalize_agent_result(ctx, result)
    return merge_manifest_metadata(finalized, render_result)


codex = agent(name="codex", install=_install, run=_run, build_env=_build_env)
