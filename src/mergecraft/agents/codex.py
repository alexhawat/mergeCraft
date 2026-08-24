"""Codex CLI agent harness — invokes ``codex exec`` with MCP config."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from loguru import logger

from mergecraft.agents.codex_stream import (
    CODEX_MODEL_REASONING_EFFORT,
    codex_stream_event_handler,
    parse_codex_payload,
)
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
    payload_shell_mode,
    spawn_agent_cli,
)
from mergecraft.agents.verifier import VERIFIER_AGENT_NAME, VERIFIER_SYSTEM_PROMPT
from mergecraft.mcp.endpoints import MCP_VERIFIER_ENDPOINT
from mergecraft.tracing.genai import resolve_capture_policy
from mergecraft.types import MERGECRAFT_MCP_NAME, MERGECRAFT_VERIFIER_MCP_NAME
from mergecraft.utils.process_group import track_process_group, wait_or_kill_process_group
from mergecraft.utils.provider_failure import is_retryable_cli_failure
from mergecraft.utils.secrets import build_agent_env

CODEX_AUTH_ENV = "CODEX_AUTH_JSON"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
# A Codex ``config.toml`` is built as a nested mapping and rendered once; a
# nested value is a table, a scalar is a key in the table that holds it.
TomlTable: TypeAlias = dict[str, "str | bool | TomlTable"]
_BARE_TOML_KEY = re.compile(r"[A-Za-z0-9_-]+")
CODEX_REVIEW_PERMISSION_PROFILE = "mergecraft-review"
# D16 — env var name that carries the per-run MCP bearer token into the Codex
# subprocess. Codex reads this via ``bearer_token_env_var`` in config.toml and
# sends it as ``Authorization: Bearer`` on every MCP request. Using a documented
# Codex transport key avoids ``socket_path`` (undocumented) and ``http_headers``
# (unverified — an unknown key can break Codex's TOML parse).
_CODEX_MCP_TOKEN_ENV: str = "MERGECRAFT_MCP_TOKEN"

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
        except (ValueError, OSError):  # fmt: skip
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
    """Render ``value`` as a TOML basic string.

    ``\\`` and ``"`` are escaped, and so is every control character TOML
    forbids raw inside a basic string — U+0000 to U+0008, U+000A to U+001F,
    and U+007F. The three with a named escape get it; the rest get ``\\uXXXX``,
    which is what ``tomli_w`` emits. A value carrying any of them otherwise
    renders a file ``tomllib`` refuses to parse, and ``base_url`` comes from a
    consumer-supplied env var, so this is reachable rather than theoretical.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    for char, replacement in (("\n", "\\n"), ("\r", "\\r"), ("\t", "\\t")):
        escaped = escaped.replace(char, replacement)
    escaped = "".join(
        f"\\u{ord(char):04x}" if ord(char) < 0x20 or ord(char) == 0x7F else char for char in escaped
    )
    return f'"{escaped}"'


def _toml_key(key: str) -> str:
    """Return ``key`` as a TOML key, quoting it when it is not a bare key."""
    return key if _BARE_TOML_KEY.fullmatch(key) else _toml_string(key)


def _render_toml(table: TomlTable, path: tuple[str, ...] = ()) -> list[str]:
    """Render a nested mapping as TOML text.

    A bare key belongs to the most recent table header, so a builder that
    appends lines has to keep every top-level key ahead of every table by hand
    — the ordering defect behind #222. Rendering from a mapping removes the
    hazard structurally: scalars of a table are always emitted directly under
    its own header, whatever order the caller populated the mapping in.

    ``tomli_w.dumps`` produces byte-identical output on the real config shape;
    this stays hand-rolled on dependency grounds, written up under "Deferred
    designs the review rounds declined" in
    ``docs/test-plans/open-issues-sweep-2026-08-19.md``.
    """
    scalars = {key: value for key, value in table.items() if not isinstance(value, dict)}
    tables = {key: value for key, value in table.items() if isinstance(value, dict)}
    lines: list[str] = []
    if path and (scalars or not tables):
        lines.append("")
        lines.append(f"[{'.'.join(_toml_key(part) for part in path)}]")
    for key, value in scalars.items():
        rendered = _toml_string(value) if isinstance(value, str) else str(value).lower()
        lines.append(f"{_toml_key(key)} = {rendered}")
    for key, sub_table in tables.items():
        lines.extend(_render_toml(sub_table, (*path, key)))
    return lines


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
        f"(config key `[mcp_servers.{MERGECRAFT_MCP_NAME}]`). The verifier "
        f"subagent uses `[mcp_servers.{MERGECRAFT_VERIFIER_MCP_NAME}]` at "
        f"``{MCP_VERIFIER_ENDPOINT}``. Tool names are "
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


def _add_custom_provider_tables(config: TomlTable) -> None:
    """Add a ``model_providers.<id>`` table for every configured custom provider.

    #71 / W3: routes ``MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}_<N>`` and
    the singleton alias into Codex CLI 0.146's ``model_providers`` config
    schema. Verified against the installed Codex CLI version pinned at
    ``Dockerfile:49`` (``@openai/codex``, locally ``codex-cli 0.146.0``) and
    the upstream ``codex-rs/model-provider-info`` schema: each block carries
    ``base_url``, ``env_key`` (referencing the env-var name, not the resolved
    value — convention 7), and ``wire_api = "responses"`` (the only
    supported wire protocol since February 2026).

    No-op when no ``MERGECRAFT_CUSTOM_PROVIDER_*`` env vars are touched at
    all. Partial pairs (only one half set) emit an empty ``model_providers``
    table; consumers reading the table find no entries and skip.
    """
    if not _has_any_custom_provider_env():
        return
    model_providers: TomlTable = {}
    config["model_providers"] = model_providers
    for record in resolve_gateway_endpoints().values():
        model_providers[record.provider_id] = {
            "name": record.provider_id,
            "base_url": record.base_url,
            "env_key": record.api_key_env,
            "wire_api": "responses",
        }


def _add_mcp_server_table(config: TomlTable, ctx: AgentRunContext) -> None:
    # D16 — Use documented Codex MCP transport: HTTP ``url`` + ``bearer_token_env_var``.
    # ``socket_path`` is not a documented Codex config key. ``http_headers`` was
    # explicitly ruled out (unverified — unknown keys can break Codex's TOML parse).
    # The per-run token is written into ``_CODEX_MCP_TOKEN_ENV`` by ``_build_env``
    # so it travels to the subprocess without appearing in config.toml.
    from mergecraft.mcp.endpoints import mcp_role_url

    reviewer_url = mcp_role_url(ctx.mcp_server_url, None)
    verifier_url = mcp_role_url(ctx.mcp_server_url, VERIFIER_AGENT_NAME)
    server_entry = {
        "url": reviewer_url,
        "bearer_token_env_var": _CODEX_MCP_TOKEN_ENV,
        # Without this, every tool call is auto-cancelled in CI. Codex
        # auto-approves an MCP call only when the permission profile grants
        # full disk write access (codex_mcp::mcp_permission_prompt_is_auto_approved),
        # and the read-only review profile does not. `approval_policy =
        # "never"` then means the elicitation is never answered, so the call
        # resolves to "user cancelled MCP tool call" — with no interactive
        # user anywhere in the pipeline. The server is ours and the action
        # already runs with push/shell disabled, so approving its tools up
        # front is the intended posture.
        "default_tools_approval_mode": "approve",
    }
    config["mcp_servers"] = {
        MERGECRAFT_MCP_NAME: {**server_entry, "url": reviewer_url},
        MERGECRAFT_VERIFIER_MCP_NAME: {**server_entry, "url": verifier_url},
    }
    # Do NOT put ctx.subagent_denied_tools into ``disabled_tools``. That list is
    # every mutates=True MCP tool (checkout_pr, create_pull_request_review, …)
    # and exists to keep *subagents* read-only. Wiring it onto the main session's
    # MCP server hides those tools from the reviewer itself, so Codex can inspect
    # a PR but can never check it out or submit a review — mergecraft-approval
    # stays neutral forever. Subagent read-only posture stays in the instructions
    # preamble (_build_subagent_instructions); Claude's harness never disabled
    # these tools for the primary agent either.


def _add_read_only_mcp_network_profile(config: TomlTable) -> None:
    profile = CODEX_REVIEW_PERMISSION_PROFILE
    config["default_permissions"] = profile
    config["permissions"] = {
        profile: {
            "extends": ":read-only",
            "network": {
                "enabled": True,
                "allow_local_binding": True,
                "domains": {
                    "api.openai.com": "allow",
                    "*.openai.com": "allow",
                    "127.0.0.1": "allow",
                    "localhost": "allow",
                },
            },
        }
    }


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
    config: TomlTable = {
        "approval_policy": "never" if os.environ.get("CI") == "true" else "on-request",
        "experimental_instructions_file": str(instructions_path),
        "model_reasoning_effort": CODEX_MODEL_REASONING_EFFORT,
    }
    # W3 / #71 — Codex passthrough for OpenAI-compatible providers. No-op
    # when no ``MERGECRAFT_CUSTOM_PROVIDER_*`` env vars are set.
    _add_custom_provider_tables(config)
    if _codex_use_permission_profiles(ctx):
        _add_read_only_mcp_network_profile(config)
    else:
        config["sandbox_mode"] = sandbox_mode
        if ctx.mcp_server_url and sandbox_mode == "workspace-write":
            config["sandbox_workspace_write"] = {"network_access": True}

    if ctx.mcp_server_url:
        _add_mcp_server_table(config, ctx)

    config_path = codex_home / "config.toml"
    config_path.write_text("\n".join(_render_toml(config)) + "\n", encoding="utf-8")
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
    # D16 — inject the per-run MCP bearer token so Codex can authenticate via
    # ``bearer_token_env_var`` in config.toml. Only inject when a token was
    # issued (dev/test runs without a live MCP server leave this empty).
    extra: dict[str, str] = {"CODEX_HOME": str(codex_home)}
    if ctx.mcp_auth_token:
        extra[_CODEX_MCP_TOKEN_ENV] = ctx.mcp_auth_token
    env = build_agent_env("codex", extra)
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


def _parse_codex_stdout(stdout: str) -> tuple[str, AgentUsage | None]:
    text = stdout.strip()
    if not text:
        return "", None

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return parse_codex_payload(data)
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
        parsed_output, parsed_usage = parse_codex_payload(event)
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
    handler, close_all_open_spans = codex_stream_event_handler(
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
        # The provider's own event is the authoritative reason; stderr is the
        # fallback, because it routinely carries benign CLI chatter (#445).
        stream_error = accumulator.stream_error
        error = stream_error or stderr_text.strip() or f"codex exited {returncode}"
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
        # Classify against the provider's message too — a stdout-only failure
        # is invisible to a stderr-only classifier (#445, #446).
        retryable = is_retryable_cli_failure(
            returncode=returncode,
            stderr=f"{stream_error or ''}\n{stderr_text}",
        )
        return AgentResult(
            success=False,
            output=output or None,
            error=error,
            usage=usage,
            metadata={"retryable": True} if retryable else {},
        )
    return AgentResult(success=True, output=output or None, usage=usage)


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
