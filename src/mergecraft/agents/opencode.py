"""OpenCode agent harness for the CLI and serve transports.

Module: mergecraft.agents.opencode
Depends: httpx, loguru, mergecraft.agents.{cli_runner,opencode_config,opencode_serve,shared}

Exports:
    OPENCODE_API_KEY_ENV — provider API key environment variable.
    OPENCODE_AUTH_ENV — environment variable containing OpenCode auth JSON.
    ProviderTimeoutError — controlled failure when the provider times out.
    build_custom_provider — emit the gateway block for a model.
    build_custom_providers_for_models — merge gateway blocks for a model roster.
    build_security_config — render the isolated review configuration.
    opencode — the registered OpenCode harness.
    opencode_applied_model_params — resolve effective model parameters for tracing.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Final

import httpx
from loguru import logger

import mergecraft.agents.openai_compatible_gateways as openai_compatible_gateways
import mergecraft.agents.opencode_config as opencode_config
import mergecraft.agents.opencode_serve as opencode_serve
from mergecraft.agents.cli_runner import CliHarnessSpec, cli_working_directory, run_cli_attempt
from mergecraft.agents.opencode_otel import apply_otel_plugin, opencode_otel_plugin_wiring
from mergecraft.agents.opencode_pricing import (
    GO_COST_NOTE,
    GO_ESTIMATED_COST_NOTE,
    estimate_go_step_cost,
)
from mergecraft.agents.opencode_tool_parts import record_opencode_part as _record_opencode_part
from mergecraft.agents.post_run import finalize_agent_result, run_post_run_retry_loop
from mergecraft.agents.shared import (
    AgentResult,
    AgentRunContext,
    AgentUsage,
    agent,
    apply_integrity_gate,
    capture_integrity_baseline,
    spawn_agent_cli,
    stderr_tail_for_error,
)
from mergecraft.security.private_files import write_private_file
from mergecraft.tracing import current_tracer
from mergecraft.tracing.genai import resolve_capture_policy
from mergecraft.tracing.http import instrument_httpx
from mergecraft.utils.process_group import track_process_group, wait_or_kill_process_group
from mergecraft.utils.provider_failure import is_retryable_cli_failure
from mergecraft.utils.secrets import build_agent_env, filter_env

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from typing import Any

    from mergecraft.agents._stream_consumer import StreamSpanAccumulator
    from mergecraft.mcp.tool_state import ToolState
    from mergecraft.security.review_integrity import TreeBaseline
    from mergecraft.utils.run_bounds import BudgetTracker


OPENCODE_AUTH_ENV = "OPENCODE_AUTH_JSON"
OPENCODE_API_KEY_ENV = "OPENCODE_API_KEY"

# Keep the existing harness import surface for callers and tests.
ProviderTimeoutError = opencode_serve.ProviderTimeoutError
build_custom_provider = opencode_config.build_custom_provider
build_custom_providers_for_models = opencode_config.build_custom_providers_for_models
build_security_config = opencode_config.build_security_config
opencode_applied_model_params = opencode_config.opencode_applied_model_params

# Compatibility aliases for callers of the former private helpers.
_SERVER_LOG_TAIL_LINES = opencode_serve.SERVER_LOG_TAIL_LINES
_ServerHandle = opencode_serve.ServerHandle
_api_key_from_env = opencode_config.api_key_from_env
_boot_opencode_server = opencode_serve.boot_opencode_server
_config_credential_env = opencode_config.config_credential_env
_evidence_dir = opencode_config.evidence_dir
_opencode_applied_model_params_from_config = (
    opencode_config.opencode_applied_model_params_from_config
)
_opencode_build_agent_overrides = opencode_config.opencode_build_agent_overrides
_opencode_generation_options = opencode_config.opencode_generation_options
_opencode_model_context_limit = opencode_config.opencode_model_context_limit
_opencode_model_entry = opencode_config.opencode_model_entry
_opencode_provider_http_timeout_s = opencode_serve.opencode_provider_http_timeout_s
_opencode_provider_options = opencode_config.opencode_provider_options
_positive_int = opencode_config.positive_int
_prompt_session = opencode_serve.prompt_session
_prompt_session_http = opencode_serve.prompt_session_http
_provider_config_for_model = openai_compatible_gateways.provider_config_for_model


def _opencode_run_config_dir(ctx: AgentRunContext) -> Path:
    """Private run-temp child holding the generated ``opencode.json``.

    Outside the evidence directory (which workflows upload) and denied to the
    reviewer by ``_TEMP_DIR_PRIVATE_CHILDREN``.
    """
    return Path(ctx.tmpdir) / "opencode-run-config"


def _opencode_data_home(ctx: AgentRunContext) -> Path:
    """Return the XDG data root parent for this run's isolated ``auth.json``."""
    return Path(ctx.tmpdir) / "opencode-xdg-data"


def _opencode_config_home(ctx: AgentRunContext) -> Path:
    """Empty per-run ``OPENCODE_CONFIG_DIR``, so the operator's global config is not loaded.

    OpenCode otherwise merges ``~/.config/opencode``: its MCP servers, plugins and
    agents join the review. A global server named ``mergecraft`` even shadows the
    run's own MCP server, leaving the agent without ``submit_review_verdict``.
    ``opencode debug config`` still lists the global file as a source with this set;
    what a run loads is pinned against the real CLI in
    ``tests/agents/test_opencode_config_isolation.py``.
    """
    return Path(ctx.tmpdir) / "opencode-xdg-config"


def _with_flat_opencode_auth(env: dict[str, str], *, model: str | None) -> dict[str, str]:
    from mergecraft.config.runtime_provider_registry import harness_env_for_active_provider

    registry_resolved = any(
        value.strip() for value in harness_env_for_active_provider(model, "opencode").values()
    )
    if not registry_resolved and OPENCODE_AUTH_ENV not in env:
        flat = os.environ.get(OPENCODE_AUTH_ENV, "").strip()
        if flat:
            env[OPENCODE_AUTH_ENV] = flat
    return env


def _hand_xdg_data_home_to_agent(data_home: Path) -> None:
    """Chown an isolated run tree (XDG data home, run config) to the agent user (W3.4).

    ``_setup_opencode_auth`` runs inside the still-root action entrypoint, so the
    ``opencode/`` directory and its ``auth.json`` are created root-owned even
    though ``data_home``'s parent — the run temp dir — is already agent-owned
    (``git_setup._prepare_temp_dir_for_agent``). Ownership follows the creating
    process, not the parent directory's owner, so the ``setpriv``-dropped
    ``opencode`` CLI cannot create ``.../opencode/log`` (the observed failure is
    ``EACCES: permission denied, mkdir '.../opencode/log'``) or read the
    ``auth.json`` it was handed. Mirror
    ``git_setup._prepare_temp_dir_for_agent``: resolve the agent user and chown
    the whole tree, but only when running as root. A non-root / dev host, or a
    platform without ``pwd``, is a silent no-op — this must never raise.

    Args:
        data_home (Path): Isolated ``XDG_DATA_HOME`` root the caller just wrote
            ``opencode/auth.json`` under.
    """
    if os.getuid() != 0 or not data_home.exists():
        return
    try:
        import pwd

        from mergecraft.utils.privilege import agent_user_name

        pw = pwd.getpwnam(agent_user_name())
    except (ImportError, KeyError):  # fmt: skip
        return
    for path in (data_home, *data_home.rglob("*")):
        with contextlib.suppress(OSError):
            if path.is_symlink():
                # Re-own the link itself, never its target, and never chmod through it:
                # a link planted in the tree must not re-own a file outside it.
                os.chown(path, pw.pw_uid, pw.pw_gid, follow_symlinks=False)
                continue
            if path.is_dir():
                os.chmod(path, 0o755)  # nosec B103 — agent must traverse the auth tree
            os.chown(path, pw.pw_uid, pw.pw_gid, follow_symlinks=False)


def _setup_opencode_auth(
    ctx: AgentRunContext,
    *,
    data_home: Path,
    credential_env: Mapping[str, str] | None = None,
) -> None:
    """Write ``auth.json`` under an isolated XDG data root for ``opencode serve``."""
    from mergecraft.security.opencode_auth import opencode_auth_usable

    source: Mapping[str, str] = credential_env if credential_env is not None else os.environ
    raw = source.get(OPENCODE_AUTH_ENV, "").strip()
    if raw and opencode_auth_usable(raw):
        auth_dir = data_home / "opencode"
        auth_dir.mkdir(parents=True, exist_ok=True)
        write_private_file(auth_dir / "auth.json", raw)
        _hand_xdg_data_home_to_agent(data_home)
        return
    if raw:
        logger.warning(
            "{} is set but not usable OpenCode auth JSON — falling back to {} when present",
            OPENCODE_AUTH_ENV,
            OPENCODE_API_KEY_ENV,
        )


def _resolved_opencode_credentials(ctx: AgentRunContext) -> dict[str, str]:
    return _with_flat_opencode_auth(
        build_agent_env("opencode", model=ctx.resolved_model),
        model=ctx.resolved_model,
    )


async def _install(_token: str | None = None) -> str:
    path = shutil.which("opencode")
    if path:
        return path
    msg = "opencode CLI not found on PATH. Install @opencode/cli or ensure `opencode` is available."
    raise FileNotFoundError(msg)


# 1.x prints ``1.18.30``; 2.x prints ``opencode v2.0.29``.
_OPENCODE_VERSION_RE: Final = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_OPENCODE_MAJOR_CACHE: dict[str, int | None] = {}


def _opencode_major_version(cli: str) -> int | None:
    """Return the OpenCode CLI's major version, or ``None`` when it cannot be read.

    Read once per binary path. ``None`` keeps the 1.x server path, which is
    what every release before 2.0 needs.
    """
    if cli in _OPENCODE_MAJOR_CACHE:
        return _OPENCODE_MAJOR_CACHE[cli]
    major: int | None = None
    try:
        process = spawn_agent_cli([cli, "--version"], env=filter_env())
        with track_process_group(process):
            try:
                stdout, stderr = process.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    wait_or_kill_process_group(process, timeout=0)
                raise
        match = _OPENCODE_VERSION_RE.search(f"{stdout}\n{stderr}")
        if match:
            major = int(match.group(1))
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("opencode --version failed: {}", exc)
    _OPENCODE_MAJOR_CACHE[cli] = major
    return major


def _parse_model(value: str | None) -> dict[str, str] | None:
    if not value:
        return None
    slash = value.find("/")
    if slash <= 0:
        return None
    return {"providerID": value[:slash], "modelID": value[slash + 1 :]}


def _capture_integrity_baseline(ctx: AgentRunContext) -> TreeBaseline | None:
    # The shared gate (#1329); kept as a module seam for the opencode pins.
    return capture_integrity_baseline(ctx)


def _apply_integrity_gate(
    result: AgentResult,
    baseline: TreeBaseline | None,
) -> AgentResult:
    return apply_integrity_gate(result, baseline)


async def _run(ctx: AgentRunContext) -> AgentResult:
    try:
        cli = await _install(None)
    except FileNotFoundError as err:
        return AgentResult(success=False, error=str(err))

    model = ctx.resolved_model
    config_json = build_security_config(ctx, model)
    # The OTel plugin targets OpenCode 2.x's event stream; 1.x runs never load it.
    major = await asyncio.to_thread(_opencode_major_version, cli)
    otel_plugin = (
        opencode_otel_plugin_wiring(ctx.tool_state.trust_tier)
        if major is not None and major >= 2
        else None
    )
    if otel_plugin is not None:
        config_json = apply_otel_plugin(config_json, otel_plugin)
    config_dir = _opencode_run_config_dir(ctx)
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "opencode.json"
    write_private_file(config_path, config_json)
    _hand_xdg_data_home_to_agent(config_dir)

    credential_env = _resolved_opencode_credentials(ctx)
    data_home = _opencode_data_home(ctx)
    config_home = _opencode_config_home(ctx)
    config_home.mkdir(parents=True, exist_ok=True)
    _setup_opencode_auth(ctx, data_home=data_home, credential_env=credential_env)

    # Baseline AFTER our own writes, before the agent runs. ``_evidence_dir``
    # falls back to ``<tmpdir>/evidence`` when neither MERGECRAFT_EVIDENCE_DIR
    # nor RUNNER_TEMP is set (evidence/run_packet.py:71); when that tmpdir sits
    # inside the checkout, hashing first would make ``opencode-run-config/opencode.json``
    # and the isolated ``auth.json`` under ``opencode-xdg-data`` — files mergeCraft
    # itself just wrote — read as tampering, and every review would fail closed.
    # The gate still covers the whole agent session, which is the mutation this
    # check exists to catch.
    baseline = _capture_integrity_baseline(ctx)
    if baseline is None:
        return AgentResult(
            success=False,
            error="review integrity baseline could not be captured; refusing read-only review",
        )

    extras: dict[str, str] = {
        "OPENCODE_CONFIG_CONTENT": config_json,
        "OPENCODE_CONFIG": str(config_path),
        "OPENCODE_CONFIG_DIR": str(config_home),
        # A reviewed repository's ``opencode.json`` / ``.opencode/`` can declare
        # plugins (code that runs in the harness) and MCP servers; never load them.
        "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
        "XDG_DATA_HOME": str(data_home),
    }
    model_s = (model or "").strip()
    bedrock_id = os.environ.get("BEDROCK_MODEL_ID", "").strip()
    vertex_id = os.environ.get("VERTEX_MODEL_ID", "").strip()
    if bedrock_id and model_s == bedrock_id:
        extras["CLAUDE_CODE_USE_BEDROCK"] = "1"
    if vertex_id and model_s == vertex_id:
        extras["CLAUDE_CODE_USE_VERTEX"] = "1"
    env = build_agent_env("opencode", extras, model=model)
    env.update({k: v for k, v in credential_env.items() if k not in env})
    # Values the config references as ``{env:NAME}``; added after the allowlist
    # filter, which strips credential-shaped names.
    env.update(_config_credential_env(ctx, config_json))
    if otel_plugin is not None:
        # Header values the plugin entry references as ``{env:NAME}``; added after
        # the allowlist filter, which would otherwise drop them.
        env.update(otel_plugin.env)

    # OpenCode 2.x serves a different HTTP API (``/api/session/...``); the
    # 1.x ``POST /session`` below gets 405. Its ``run`` command keeps the JSON
    # event stream and resumes a session by id, so 2.x reviews go through it.
    if major is not None and major >= 2:
        return _apply_integrity_gate(
            await _run_v2(cli=cli, ctx=ctx, env=env, model=model),
            baseline,
        )

    # Prefer serve + HTTP when available; fall back to `opencode run`.
    #
    # Boot runs on a worker thread: it waits on a URL event with a deadline and
    # drains both pipes, so it must never block the event loop (P5). The cancel
    # event lets ``_run``'s own cancellation reach the worker, which kills and
    # reaps the serve group before ``_run`` propagates CancelledError (#449).
    cancel = threading.Event()
    boot_handle: list[_ServerHandle] = []
    boot_error: list[Exception] = []

    def _boot() -> None:
        try:
            boot_handle.append(
                _boot_opencode_server(
                    cli=cli, env=env, cwd=cli_working_directory(ctx), cancel=cancel
                )
            )
        except Exception as err:
            boot_error.append(err)

    boot_thread = threading.Thread(target=_boot, name="opencode-serve-boot", daemon=True)
    boot_thread.start()
    try:
        await asyncio.to_thread(boot_thread.join)
    except asyncio.CancelledError:
        # Wake the worker, wait for it to kill and reap the group, then
        # re-raise so the cancellation is never swallowed.
        cancel.set()
        await asyncio.to_thread(boot_thread.join)
        if boot_handle:
            boot_handle[0].close()
        raise

    if boot_error:
        logger.info("opencode serve unavailable ({}), falling back to run", boot_error[0])
        return _apply_integrity_gate(
            await _run_cli_fallback(cli=cli, ctx=ctx, env=env),
            baseline,
        )

    handle = boot_handle[0]
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # T2 / D8 — see ``_prompt_session`` for the same wrap; the
            # opencode serve + session bootstrap request goes through this
            # client, so it must emit ``http.client.request`` spans too.
            instrument_httpx(client, tracer=current_tracer())
            created = await client.post(
                f"{handle.base_url}/session",
                json={"title": "mergecraft"},
            )
            if created.status_code >= 400:
                return _apply_integrity_gate(
                    AgentResult(
                        success=False,
                        error=f"failed to create opencode session: {created.text[:300]}",
                    ),
                    baseline,
                )
            session = created.json()
            session_id = str(session.get("id") or session.get("sessionID") or "")
            if not session_id:
                return _apply_integrity_gate(
                    AgentResult(success=False, error="opencode session missing id"),
                    baseline,
                )

        model_obj = _parse_model(model)
        system = ctx.instructions.system
        user = ctx.instructions.user
        prompt = f"{system}\n\n{user}".strip() if system else user

        # OB3 — the trust tier is ``derive_trust_tier()``'s output carried on
        # the tool state, never an env fallback (D7 — the untrusted content
        # cap must not be defeatable by environment control).
        capture_policy = resolve_capture_policy(ctx.tool_state.trust_tier)

        async def resume(followup: str) -> AgentResult:
            return await _prompt_session(
                base_url=handle.base_url,
                session_id=session_id,
                text=followup,
                model=model_obj,
                resolved_model=model,
                capture_policy=capture_policy,
                tool_state=ctx.tool_state,
            )

        try:
            # The initial prompt carries the whole review and is by far the
            # likeliest place to time out, so it must sit inside the same
            # handler as the retry loop (#444). Left outside, a timeout here
            # propagated out of ``run_once`` and aborted the chain with no
            # fallback — the exact failure this branch exists to fix.
            initial = await _prompt_session(
                base_url=handle.base_url,
                session_id=session_id,
                text=prompt,
                model=model_obj,
                resolved_model=model,
                capture_policy=capture_policy,
                tool_state=ctx.tool_state,
            )
            result = await run_post_run_retry_loop(ctx, initial=initial, resume=resume)
        except ProviderTimeoutError as exc:
            # Controlled domain error: surface as a clean failed attempt
            # rather than letting a raw httpx traceback abort the review.
            # Without an accepted verdict, ``retryable`` lets the model chain
            # advance (#444). Finalize first so a verdict accepted before the
            # timeout remains the winner, subject to the integrity gate.
            # httpx.ReadTimeout stringifies to nothing, so without the server's
            # own tail the operator gets a bare "timed out:" and no lead (#449).
            tail = handle.recent_output()
            detail = f"{exc}\n\nrecent opencode serve output:\n{tail}" if tail else str(exc)
            return _apply_integrity_gate(
                await finalize_agent_result(
                    ctx,
                    AgentResult(
                        success=False,
                        error=detail,
                        metadata={"retryable": True},
                    ),
                ),
                baseline,
            )
        return _apply_integrity_gate(
            await finalize_agent_result(ctx, result),
            baseline,
        )
    finally:
        handle.close()


# One argv string may hold at most 128 KiB (Linux ``MAX_ARG_STRLEN``); a
# longer prompt rides in an attached file instead.
_OPENCODE_ARGV_PROMPT_LIMIT: Final = 120_000


def _opencode_prompt_args(ctx: AgentRunContext, text: str) -> list[str]:
    """Return the ``opencode run`` prompt arguments for ``text`` (#1329).

    A prompt within one argv string's limit is passed as is; a longer one is
    written to a file and attached with ``--file``. Shared by the 2.x run path
    and the 1.x ``run`` fallback, which used to pass every prompt as argv.
    """
    if len(text.encode("utf-8")) <= _OPENCODE_ARGV_PROMPT_LIMIT:
        return [text]
    prompt_dir = _evidence_dir(ctx)
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = prompt_dir / f"opencode-prompt-{time.time_ns()}.md"
    prompt_path.write_text(text, encoding="utf-8")
    return ["--file", str(prompt_path), "Follow the instructions in the attached file."]


async def _run_v2(
    *, cli: str, ctx: AgentRunContext, env: dict[str, str], model: str | None
) -> AgentResult:
    """Run one review on OpenCode 2.x through ``opencode run``.

    ``--standalone`` gives the run a private server: without it 2.x attaches
    to a shared background service that outlives the run. Follow-up prompts
    from the post-run retry loop resume the same session with ``--session``.
    """
    system = ctx.instructions.system
    user = ctx.instructions.user
    prompt = f"{system}\n\n{user}".strip() if system else user
    base = [cli, "run", "--standalone", "--format", "json", "--title", "mergecraft"]
    if model:
        base.extend(["--model", model])
    session: dict[str, str] = {}

    async def _turn(text: str, session_id: str | None = None) -> AgentResult:
        cmd = list(base)
        if session_id:
            cmd.extend(["--session", session_id])
        cmd.extend(_opencode_prompt_args(ctx, text))
        return await asyncio.to_thread(
            _run_opencode_cli_streaming, cmd=cmd, ctx=ctx, env=env, session=session
        )

    initial = await _turn(prompt)
    if not initial.success:
        # The CLI may fail after accepting a verdict; carry it to the chain
        # classifier without resuming the failed turn.
        return await finalize_agent_result(ctx, initial)

    async def resume(followup: str) -> AgentResult:
        session_id = session.get("id")
        if not session_id:
            return AgentResult(
                success=False,
                error="opencode run reported no session id; the follow-up cannot resume it",
            )
        return await _turn(followup, session_id)

    result = await run_post_run_retry_loop(ctx, initial=initial, resume=resume)
    return await finalize_agent_result(ctx, result)


async def _run_cli_fallback(*, cli: str, ctx: AgentRunContext, env: dict[str, str]) -> AgentResult:
    """Run the review through ``opencode run`` when ``opencode serve`` cannot boot (1.x).

    The session handler keeps the model's text answer and the session id, and
    a long prompt is attached as a file, as on the 2.x path (#1329). Follow-up
    prompts from the post-run retry loop resume that session.
    """
    prompt = ctx.instructions.user
    if ctx.instructions.system:
        prompt = f"{ctx.instructions.system}\n\n{prompt}"
    base = [cli, "run", "--format", "json"]
    if ctx.resolved_model:
        base.extend(["--model", ctx.resolved_model])
    session: dict[str, str] = {}

    async def _turn(text: str, session_id: str | None = None) -> AgentResult:
        cmd = list(base)
        if session_id:
            cmd.extend(["--session", session_id])
        cmd.extend(_opencode_prompt_args(ctx, text))
        # W6 migration: opencode ``--format json`` may emit multiple NDJSON
        # events. We attempt the streaming read loop and fall back to the
        # legacy last-line parse if the events are not granular enough (D12).
        # Blocking Popen/wait runs in a worker thread so outer wait_for can preempt.
        return await asyncio.to_thread(
            _run_opencode_cli_streaming, cmd=cmd, ctx=ctx, env=env, session=session
        )

    initial = await _turn(prompt)

    async def resume(followup: str) -> AgentResult:
        session_id = session.get("id")
        if not session_id:
            return AgentResult(
                success=False,
                error="opencode run reported no session id; the follow-up cannot resume it",
            )
        return await _turn(followup, session_id)

    result = await run_post_run_retry_loop(ctx, initial=initial, resume=resume)
    return await finalize_agent_result(ctx, result)


def _run_opencode_cli_streaming(
    *,
    cmd: list[str],
    ctx: AgentRunContext,
    env: dict[str, str],
    session: dict[str, str] | None = None,
) -> AgentResult:
    """Streaming read loop for ``opencode run --format json`` (W6).

    Opencode's JSON output is **partial** (W0.5) — events may not be
    granular enough for per-tool spans. We attempt the streaming read
    and degrade to run-level spans if the events lack the required
    fields (D12).
    """
    from mergecraft.agents._stream_consumer import (
        StreamSpanAccumulator,
    )
    from mergecraft.tracing.sinks import claim_sink

    # The ``run`` stream carries the session's tool parts as they finish, reads
    # included. The HTTP path does not claim this: it sees what a response returns.
    ctx.tool_state.driver_reports_reads = True
    accumulator = StreamSpanAccumulator(agent_name="opencode")
    # W4 H7 — the legacy code claimed a sink and built a Tracer but discarded it.
    # Opencode's stream handler is currently a no-op closure, so the tracer had
    # no observer to wire into. We keep the resolve + claim path so the sink
    # is still claimed (preventing the NullSink fallback during this run), but
    # we no longer construct the unused Tracer. If opencode gains real
    # stream handlers in the future, wire the Tracer into ``consume_stream``
    # here.
    try:
        from mergecraft.tracing.resolve import resolve_active_tracing

        claim_sink(resolve_active_tracing())
    except Exception as exc:
        logger.debug("opencode stream tracer resolution failed: {}", exc)

    handler = (
        _session_event_handler(
            session,
            tool_state=ctx.tool_state,
            model=ctx.resolved_model,
            budget_tracker=ctx.budget_tracker,
        )
        if session is not None
        else _bash_only_handler(
            ctx.tool_state,
            model=ctx.resolved_model,
            budget_tracker=ctx.budget_tracker,
        )
    )

    def classify(returncode: int, stderr_text: str) -> AgentResult:
        if accumulator.halt_reason:
            return AgentResult(
                success=False,
                error=f"token budget exhausted during review: {accumulator.halt_reason}",
                metadata={"retryable": False, "budget_exhausted": True},
                usage=_priced_stream_usage(accumulator, ctx=ctx),
            )
        if returncode != 0:
            stream_error = (session or {}).get("error", "")
            retryable = is_retryable_cli_failure(
                returncode=returncode, stderr=f"{stream_error}\n{stderr_text}"
            )
            # A failed attempt still burns tokens — often the attempt that
            # escalates to the next model — so its usage belongs in the budget band
            # (claude.py and codex.py report it on the same path).
            failure_error = (stream_error or "").strip() or stderr_tail_for_error(stderr_text)
            return AgentResult(
                success=False,
                error=failure_error or f"opencode failed (exit {returncode})",
                metadata={"retryable": True} if retryable else {},
                usage=_priced_stream_usage(accumulator, ctx=ctx),
            )
        return AgentResult(
            success=True,
            output=accumulator.final_output or None,
            usage=_priced_stream_usage(accumulator, ctx=ctx),
        )

    return run_cli_attempt(
        CliHarnessSpec(
            label="opencode",
            command=cmd,
            env=env,
            accumulator=accumulator,
            handler=handler,
            classify=classify,
            usage=lambda: _priced_stream_usage(accumulator, ctx=ctx),
        ),
        ctx,
    )


def _priced_stream_usage(
    accumulator: StreamSpanAccumulator, *, ctx: AgentRunContext
) -> AgentUsage | None:
    """Return the stream's token usage, priced from the catalog when unpriced.

    OpenCode 2.x reports its own cost per step; when a provider omits it, the
    catalog fills it in the same way the session path does, so the run record
    and the packet agree on their recorded reviewer model costs.
    """
    usage = accumulator.to_usage()
    if usage is None:
        return usage
    if usage.cost_usd is not None and usage.cost_usd > 0:
        return usage
    if usage.cost_usd is not None:
        # OpenCode emits ``cost: 0`` when it cannot price the model, which is
        # "unknown", not "free" — let the catalog try.
        usage = replace(usage, cost_usd=None)
    from mergecraft.agents.curated_model_catalog import apply_catalog_cost_to_usage

    return apply_catalog_cost_to_usage(usage, model=ctx.resolved_model)


def _absorb_step_usage(
    accumulator: StreamSpanAccumulator,
    event: dict[str, Any],
    *,
    model: str | None = None,
    budget_tracker: BudgetTracker | None = None,
) -> None:
    """Fold a 2.x step's reported tokens into the run's usage (#801).

    OpenCode's ``step_finish`` part carries five **disjoint** counters:
    ``input`` is the non-cached prompt, ``output`` the visible completion,
    ``reasoning`` separate from it, and ``cache.read`` / ``cache.write`` the
    cached prompt halves. The CLI's own ``TokenUsage.total()`` sums all five, and
    it bills ``cache.read``/``cache.write`` separately and ``output`` +
    ``reasoning`` together, so the accumulator is fed the same way: cached
    prompt tokens are Anthropic-style additive, and reasoning joins the output
    total.
    """
    if event.get("type") != "step_finish":
        return
    part = event.get("part")
    if not isinstance(part, dict):
        return
    tokens = part.get("tokens")
    if not isinstance(tokens, dict):
        return
    cache = tokens.get("cache")
    cache = cache if isinstance(cache, dict) else {}
    payload: dict[str, Any] = {
        "input_tokens": tokens.get("input") or 0,
        "output_tokens": (tokens.get("output") or 0) + (tokens.get("reasoning") or 0),
        "cache_read_input_tokens": cache.get("read") or 0,
        "cache_creation_input_tokens": cache.get("write") or 0,
    }
    cost = part.get("cost")
    if isinstance(cost, (int, float)):
        payload["cost_usd"] = float(cost)
    cost_usd: float | None = None
    if (model or "").startswith("opencode-go/"):
        if isinstance(cost, (int, float)) and cost > 0:
            accumulator.cost_note = accumulator.cost_note or GO_COST_NOTE
            cost_usd = float(cost)
        else:
            estimate = estimate_go_step_cost(
                model=model,
                input_tokens=int(payload["input_tokens"]),
                output_tokens=int(payload["output_tokens"]),
                cache_read_tokens=int(payload["cache_read_input_tokens"]),
                cache_write_tokens=int(payload["cache_creation_input_tokens"]),
                timestamp_ms=event.get("timestamp"),
            )
            if estimate is not None and estimate > 0:
                payload["cost_usd"] = estimate
                cost_usd = estimate
                accumulator.cost_note = GO_ESTIMATED_COST_NOTE
    elif isinstance(cost, (int, float)) and cost > 0:
        cost_usd = float(cost)

    from mergecraft.agents.stream_budget import charge_review_stream_step
    from mergecraft.agents.token_budget import current_run_budget

    stop = charge_review_stream_step(
        payload,
        budget_tracker=budget_tracker,
        provider_budget=current_run_budget(),
        cost_usd=cost_usd,
    )
    if stop:
        accumulator.halt_reason = stop
        return
    accumulator.absorb_usage(payload)


def _bash_only_handler(
    tool_state: ToolState | None,
    *,
    model: str | None = None,
    budget_tracker: BudgetTracker | None = None,
) -> Callable[[StreamSpanAccumulator, dict[str, Any]], None]:
    """Stream handler for a run with no session: record tool calls, touch nothing else."""

    def _handle(accumulator: StreamSpanAccumulator, event: dict[str, Any]) -> None:
        _absorb_step_usage(accumulator, event, model=model, budget_tracker=budget_tracker)
        if event.get("type") == "tool_use":
            _record_opencode_part(tool_state, event.get("part"))

    return _handle


def _session_event_handler(
    session: dict[str, str],
    *,
    tool_state: ToolState | None = None,
    model: str | None = None,
    budget_tracker: BudgetTracker | None = None,
) -> Callable[[StreamSpanAccumulator, dict[str, Any]], None]:
    """Record a 2.x ``run`` stream's session id and answer text.

    Each event carries ``sessionID``; ``text`` events carry the answer in
    ``part.text``. 2.x reports a failed turn as an ``error`` event on stdout,
    not on stderr, so its message is kept for the failure the run returns.
    """

    def _handle(accumulator: StreamSpanAccumulator, event: dict[str, Any]) -> None:
        session_id = event.get("sessionID")
        if isinstance(session_id, str) and session_id:
            session.setdefault("id", session_id)
        if event.get("type") == "error":
            detail = event.get("error")
            message = (
                detail.get("message") or detail.get("data") or detail
                if isinstance(detail, dict)
                else detail
            )
            session["error"] = str(message or event)[:1000]
            accumulator.set_stream_error(session["error"])
        _absorb_step_usage(accumulator, event, model=model, budget_tracker=budget_tracker)
        part = event.get("part")
        if event.get("type") == "tool_use":
            _record_opencode_part(tool_state, part)
        if event.get("type") == "text" and isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str) and text:
                accumulator.set_output(f"{accumulator.final_output or ''}{text}")

    return _handle


opencode = agent(name="opencode", install=_install, run=_run, module_file=__file__)
