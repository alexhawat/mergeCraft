"""OpenCode agent harness — invokes `opencode` CLI / serve."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final

import httpx
from loguru import logger

from mergecraft.agents.gates import build_opencode_native_fs_permission
from mergecraft.agents.openai_compatible_gateways import (
    CUSTOM_PROVIDER_API_KEY_ENV,
    CUSTOM_PROVIDER_BASE_URL_ENV,
    SINGLETON_PROVIDER_ID,
    ProviderConfig,
    _provider_config_for_model,
    resolve_gateway_endpoint,
    resolve_gateway_endpoints,
)
from mergecraft.agents.post_run import finalize_agent_result, run_post_run_retry_loop
from mergecraft.agents.shared import (
    AgentResult,
    AgentRunContext,
    AgentUsage,
    agent,
    log_token_table,
    mcp_auth_headers,
    resolve_cache_read,
    spawn_agent_cli,
)
from mergecraft.tracing import current_tracer
from mergecraft.tracing.genai import (
    ModelParams,
    input_messages_attrs,
    model_params_from_mapping,
    output_messages_attrs,
    request_attrs,
    resolve_capture_policy,
    usage_attrs_from_agent_usage,
    usage_unavailable_attrs,
)
from mergecraft.tracing.http import instrument_httpx
from mergecraft.types import MERGECRAFT_MCP_NAME
from mergecraft.utils.privilege import agent_subprocess_env, wrap_agent_command
from mergecraft.utils.process_group import (
    kill_process_group,
    register_process_group,
    track_process_group,
    unregister_process_group,
    wait_or_kill_process_group,
)
from mergecraft.utils.retry_policy import is_retryable_cli_failure
from mergecraft.utils.secrets import build_agent_env

if TYPE_CHECKING:
    from mergecraft.tracing.content import ContentCapture

# Re-exported for tests / callers that import these names from opencode.
__all_gateway_envs__ = (CUSTOM_PROVIDER_BASE_URL_ENV, CUSTOM_PROVIDER_API_KEY_ENV)

# OpenCode provider.options accepts transport keys only — generation knobs belong
# on model entries (``limit`` / ``options``) or the primary ``build`` agent.
_OPENCODE_PROVIDER_OPTION_KEYS: frozenset[str] = frozenset(
    {
        "timeout",
        "headerTimeout",
        "chunkTimeout",
        "setCacheKey",
        "enterpriseUrl",
    }
)
_OPENCODE_LIMIT_SOURCE_KEYS: frozenset[str] = frozenset({"context_limit", "context", "max_tokens"})
# OpenCode provider HTTP reads can outlast the generic 600s external-op default
# (Nous inference hung ~10min in PR #442). Match the workflow action timeout
# (25m) so httpx does not abort before the Action's own budget.
_OPENCODE_PROVIDER_HTTP_TIMEOUT_DEFAULT_S: Final[float] = 1500.0


def _opencode_provider_http_timeout_s() -> float:
    """Return the httpx timeout for OpenCode provider HTTP session calls."""
    raw = os.environ.get("MERGECRAFT_EXTERNAL_OPERATION_TIMEOUT_S", "").strip()
    if raw:
        return float(raw)
    return _OPENCODE_PROVIDER_HTTP_TIMEOUT_DEFAULT_S


class ProviderTimeoutError(RuntimeError):
    """Raised when the opencode provider endpoint times out.

    This is a controlled domain error so callers (``shared.run`` /
    ``review.offline_agent.run_offline_agent_review``) treat the attempt as a clean failure
    instead of letting a raw ``httpx.ReadTimeout`` traceback abort the whole
    review.
    """


def _api_key_from_env(api_key_env: str) -> str:
    """Read a provider API key from the environment at emit time (HA1 / D16)."""
    return os.environ.get(api_key_env, "").strip()


def _positive_int(value: object) -> int | None:
    """Return a positive integer from a wire value, or ``None`` when absent/invalid."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer():
        as_int = int(value)
        return as_int if as_int > 0 else None
    return None


def _opencode_provider_options(config: ProviderConfig) -> dict[str, object]:
    """Build OpenCode provider ``options`` (transport only — no generation knobs)."""
    options: dict[str, object] = {
        "baseURL": config.base_url,
        "apiKey": _api_key_from_env(config.api_key_env),
    }
    for key in _OPENCODE_PROVIDER_OPTION_KEYS:
        value = config.extra_options.get(key)
        if value is not None:
            options[key] = value
    return options


def _opencode_generation_options(extra_options: dict[str, object]) -> dict[str, object]:
    """Return gateway generation knobs for OpenCode model/agent config."""
    reserved = _OPENCODE_PROVIDER_OPTION_KEYS | _OPENCODE_LIMIT_SOURCE_KEYS
    return {
        key: value
        for key, value in extra_options.items()
        if key not in reserved and value is not None
    }


def _opencode_applied_model_params_from_config(
    config: ProviderConfig | None,
) -> ModelParams | None:
    """Resolve ModelParams that the OpenCode config path actually applies (O4)."""
    if config is None or not config.extra_options:
        return None
    applied_raw: dict[str, object] = dict(_opencode_generation_options(config.extra_options))
    max_tokens = _positive_int(config.extra_options.get("max_tokens"))
    context = _opencode_model_context_limit(config)
    if max_tokens is not None and context is not None:
        applied_raw["max_tokens"] = max_tokens
    params = model_params_from_mapping(applied_raw)
    return None if params == ModelParams() else params


def opencode_applied_model_params(model: str | None) -> ModelParams | None:
    """Resolve applied ModelParams for a model slug."""
    config = _provider_config_for_model(model) if model else None
    return _opencode_applied_model_params_from_config(config)


def _opencode_build_agent_overrides(config: ProviderConfig | None) -> dict[str, object]:
    """Primary-agent overrides OpenCode reads for temperature/top_p on serve runs."""
    params = _opencode_applied_model_params_from_config(config)
    if params is None:
        return {}
    overrides: dict[str, object] = {}
    if params.temperature is not None:
        overrides["temperature"] = params.temperature
    if params.top_p is not None:
        overrides["top_p"] = params.top_p
    return overrides


def _opencode_model_context_limit(config: ProviderConfig) -> int | None:
    """Resolve an authoritative context window for OpenCode ``limit.context``."""
    if config.context_limit is not None and config.context_limit > 0:
        return config.context_limit
    for key in ("context_limit", "context"):
        resolved = _positive_int(config.extra_options.get(key))
        if resolved is not None:
            return resolved
    return None


def _opencode_model_entry(model_id: str, config: ProviderConfig) -> dict[str, object]:
    """Build one OpenCode model table entry.

    OpenCode 1.18.x requires both ``limit.context`` and ``limit.output`` when a
    ``limit`` object is present; emit it only when both values are known.
    """
    entry: dict[str, object] = {"name": model_id}
    max_tokens = _positive_int(config.extra_options.get("max_tokens"))
    context = _opencode_model_context_limit(config)
    if max_tokens is not None and context is not None:
        entry["limit"] = {"context": context, "output": max_tokens}
    generation_options = _opencode_generation_options(config.extra_options)
    if generation_options:
        entry["options"] = generation_options
    return entry


def _opencode_provider_block(
    config: ProviderConfig,
    *,
    model_id: str | None = None,
    provider_name: str | None = None,
) -> dict[str, object]:
    models: dict[str, object] = {}
    if model_id:
        models[model_id] = _opencode_model_entry(model_id, config)
    return {
        "npm": "@ai-sdk/openai-compatible",
        "name": provider_name or config.provider_id,
        "options": _opencode_provider_options(config),
        "models": models,
    }


def build_custom_provider(model: str | None) -> dict[str, object] | None:
    """Describe an OpenAI-compatible provider (or several) for opencode.

    Resolution order (W3 / #71):

    1. **Multi-provider first**: ``MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}_<N>``
       env-var pairs (operator-locked) emit one provider block per index
       under ``provider_<N>``. Gaps are preserved, partial pairs dropped,
       singleton ignored when any indexed pair is set. The active model's
       provider gets the model-id mapping; the rest are emitted with an
       empty ``models`` table so the harness can still resolve fallbacks at
       runtime.
    2. **Singleton back-compat alias**: ``MERGECRAFT_CUSTOM_PROVIDER_BASE_URL``
       + ``MERGECRAFT_CUSTOM_PROVIDER_API_KEY`` (PR #79 / D7) emit a single
       provider block keyed by the model's prefix (``default`` for the
       canonical ``default/...`` model, ``nous`` for ``nous/...``, etc.).
       This preserves the W1.1 single-provider regression pin's emitted
       shape: a singleton + ``nous/...`` model still produces a
       ``provider.nous`` block, not a ``provider.default`` one.
    3. **Named presets**: ``nous/*`` via ``NOUS_API_KEY``, ``tokenhub/*`` via
       ``TOKENHUB_API_KEY`` (optional ``NOUS_BASE_URL`` / ``TOKENHUB_BASE_URL``).
    """
    providers = resolve_gateway_endpoints()
    slash = model.find("/") if model else -1
    active_provider_id = model[:slash].lower() if (model and slash > 0) else None
    active_model_id = model[slash + 1 :] if (model and slash > 0) else None

    if providers:
        # Multi-provider path (W3). If the active model's provider id is in
        # the resolver dict, use that record; otherwise fall through to the
        # singleton/preset fallback so a model whose prefix is not registered
        # still surfaces a useful block (PR #79 compatibility).
        if active_provider_id is not None and active_provider_id in providers:
            active_record = providers[active_provider_id]
            out: dict[str, object] = {}
            for record in providers.values():
                model_id = active_model_id if record is active_record else None
                out[record.provider_id] = _opencode_provider_block(
                    record,
                    model_id=model_id,
                )
            return out
        # Fall through to legacy preset path — the active model is not in
        # the resolver dict, so use the singleton (or preset) record keyed
        # by the model's prefix.
    config = _provider_config_for_model(model) if model else None
    if config is None or not model:
        return None
    model_id = model[model.find("/") + 1 :]
    provider_key = config.provider_id
    if provider_key == SINGLETON_PROVIDER_ID and active_provider_id:
        provider_key = active_provider_id
    return {
        provider_key: _opencode_provider_block(
            config,
            model_id=model_id,
            provider_name=provider_key,
        )
    }


def _custom_provider_ids(model: str | None) -> list[str]:
    """Return provider ids to register as ``enabled_providers`` for the model.

    Mirrors :func:`build_custom_provider`'s resolution order — multi-provider
    (W3), then singleton, then named presets — so the harness enables every
    provider the configuration surfaces, including fallbacks for the chain
    walk.
    """
    providers = resolve_gateway_endpoints()
    if providers:
        slash = model.find("/") if model else -1
        active = model[:slash].lower() if (model and slash > 0) else None
        if active is not None and active in providers:
            return sorted(providers.keys())
        # Fall through to legacy resolution.
    endpoint = resolve_gateway_endpoint(model)
    if endpoint is None:
        return []
    return [endpoint[0]]


def build_security_config(ctx: AgentRunContext, model: str | None) -> str:
    from mergecraft.agents.harness_render import render_for_run

    fs_perm = build_opencode_native_fs_permission()
    render_result = render_for_run(ctx, "opencode")
    agent_block = render_result.payload["agent"] if isinstance(render_result.payload, dict) else {}
    config: dict[str, object] = {
        "permission": {
            "bash": "deny",
            "edit": fs_perm["edit"],
            "read": fs_perm["read"],
            "webfetch": "allow",
            "external_directory": "allow",
            "skill": "allow",
        },
        "mcp": {
            MERGECRAFT_MCP_NAME: {
                "type": "remote",
                "url": ctx.mcp_server_url,
                "timeout": 300_000,
                **({"headers": mcp_auth_headers(ctx)} if ctx.mcp_auth_token else {}),
            }
        },
        "agent": agent_block,
    }
    if model:
        config["model"] = model
        provider_ids = _custom_provider_ids(model)
        if provider_ids:
            config["enabled_providers"] = provider_ids
        else:
            slash = model.find("/")
            if slash > 0:
                config["enabled_providers"] = [model[:slash].lower()]
        provider_config = _provider_config_for_model(model)
        build_overrides = _opencode_build_agent_overrides(provider_config)
        if build_overrides and isinstance(agent_block, dict):
            agents = dict(agent_block)
            existing_build = agents.get("build")
            if isinstance(existing_build, dict):
                agents["build"] = {**existing_build, **build_overrides}
            else:
                agents["build"] = build_overrides
            config["agent"] = agents
    provider = build_custom_provider(model)
    if provider is not None:
        config["provider"] = provider
    return json.dumps(config)


async def _install(_token: str | None = None) -> str:
    path = shutil.which("opencode")
    if path:
        return path
    msg = "opencode CLI not found on PATH. Install opencode-ai or ensure `opencode` is available."
    raise FileNotFoundError(msg)


class _ServerHandle:
    def __init__(self, base_url: str, proc: subprocess.Popen[bytes]) -> None:
        self.base_url = base_url
        self.proc = proc
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        pid = self.proc.pid
        if self.proc.poll() is None:
            kill_process_group(pid)
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    self.proc.kill()
        unregister_process_group(pid)


def _boot_opencode_server(*, cli: str, env: dict[str, str], cwd: str) -> _ServerHandle:
    # Wrap argv with setpriv, then patch HOME/USER/LOGNAME to match the
    # dropped-to agent user (setpriv does not reset $HOME itself — see
    # mergecraft.utils.privilege.agent_subprocess_env). This is the exact
    # bug behind "opencode serve exited early: EACCES: permission denied,
    # mkdir '/github/home/.local'": opencode inherited the container's
    # HOME=/github/home, which the dropped-to uid cannot write under.
    wrapped_cmd = wrap_agent_command([cli, "serve", "--port", "0", "--hostname", "127.0.0.1"])
    resolved_env = agent_subprocess_env(env)
    proc = subprocess.Popen(
        wrapped_cmd,
        cwd=cwd,
        env=resolved_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    assert proc.stdout is not None
    base_url: str | None = None
    deadline = time.time() + 30
    buf = b""
    while time.time() < deadline:
        if proc.poll() is not None:
            err = (proc.stderr.read() if proc.stderr else b"").decode()
            msg = f"opencode serve exited early: {err}"
            raise RuntimeError(msg)
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.05)
            continue
        buf += line
        text = line.decode("utf-8", errors="replace")
        logger.debug("[opencode serve] {}", text.strip())
        match = re.search(r"https?://[^\s]+", text)
        if match:
            base_url = match.group(0).rstrip("/")
            break
    if not base_url:
        kill_process_group(proc.pid)
        msg = "opencode serve did not print a listening URL"
        raise RuntimeError(msg)
    register_process_group(proc.pid)
    return _ServerHandle(base_url=base_url, proc=proc)


def _parse_model(value: str | None) -> dict[str, str] | None:
    if not value:
        return None
    slash = value.find("/")
    if slash <= 0:
        return None
    return {"providerID": value[:slash], "modelID": value[slash + 1 :]}


async def _prompt_session(
    *,
    base_url: str,
    session_id: str,
    text: str,
    model: dict[str, str] | None,
    resolved_model: str | None = None,
    capture_policy: ContentCapture | None = None,
) -> AgentResult:
    """Prompt the opencode session — the one harness path with full payload visibility.

    OB3: unlike the CLI harnesses (whose NDJSON streams surface only
    agent-level text), this HTTP path sees the actual prompt sent and the
    completion returned, so it wraps the exchange in an ``llm.call`` span
    carrying the request model, the policy-gated input/output messages
    (O5), and the token usage. The executed model is NOT stamped: the
    opencode session response does not reliably report it, and a guessed
    value would fake the D11 fallback signal (coverage recorded in
    ``agents/_stream_consumer.py``). Tracing never fails the run
    (convention 3) — every capture step degrades to missing attrs.
    """
    tracer = current_tracer()
    if tracer is None:
        return await _prompt_session_http(
            base_url=base_url, session_id=session_id, text=text, model=model
        )
    model_slug = f"{model['providerID']}/{model['modelID']}" if model else None
    gen_ai_system = model.get("providerID") if model else None
    with tracer.start_span("llm.call") as span:
        try:
            if gen_ai_system:
                span.set_attribute("gen_ai.system", gen_ai_system)
            model_params = opencode_applied_model_params(resolved_model or model_slug)
            for key, value in request_attrs(model=model_slug, params=model_params).items():
                span.set_attribute(key, value)
            if capture_policy is not None:
                for key, value in input_messages_attrs(
                    [{"role": "user", "content": text}], policy=capture_policy
                ).items():
                    span.set_attribute(key, value)
        except Exception as exc:
            logger.debug("opencode llm.call request attrs failed: {}", exc)
        result = await _prompt_session_http(
            base_url=base_url, session_id=session_id, text=text, model=model
        )
        try:
            if result.usage is not None:
                for key, value in usage_attrs_from_agent_usage(
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                    cache_read_tokens=result.usage.cache_read_tokens,
                    cache_write_tokens=result.usage.cache_write_tokens,
                    cost_usd=result.usage.cost_usd,
                ).items():
                    span.set_attribute(key, value)
            else:
                for key, value in usage_unavailable_attrs().items():
                    span.set_attribute(key, value)
            if capture_policy is not None and result.output:
                for key, value in output_messages_attrs(
                    [{"role": "assistant", "content": result.output}],
                    policy=capture_policy,
                ).items():
                    span.set_attribute(key, value)
            if not result.success and result.error:
                span.set_status("error", result.error[:200])
        except Exception as exc:
            logger.debug("opencode llm.call response attrs failed: {}", exc)
        return result


async def _prompt_session_http(
    *,
    base_url: str,
    session_id: str,
    text: str,
    model: dict[str, str] | None,
) -> AgentResult:
    payload: dict[str, object] = {
        "parts": [{"type": "text", "text": text}],
    }
    if model:
        payload["model"] = model
    async with httpx.AsyncClient(timeout=_opencode_provider_http_timeout_s()) as client:
        # T2 / D8 — narrow instrumentation: wrap clients mergeCraft builds
        # (the custom OpenAI-compatible provider path) so every outbound
        # ``send`` emits an ``http.client.request`` span. ``current_tracer``
        # resolves to the active mergeCraft span's tracer or ``None`` when
        # tracing is disabled — ``instrument_httpx`` no-ops in that case
        # without setting the idempotency sentinel so a later activation
        # is possible.
        instrument_httpx(client, tracer=current_tracer())
        try:
            resp = await client.post(
                f"{base_url}/session/{session_id}/message",
                json=payload,
            )
            if resp.status_code >= 400:
                # Fallback path for older/newer API shapes
                resp = await client.post(
                    f"{base_url}/session/{session_id}/prompt",
                    json=payload,
                )
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.TimeoutException) as exc:
            logger.warning("opencode provider request timed out: {}", exc)
            raise ProviderTimeoutError(f"opencode provider request timed out: {exc}") from exc
        if resp.status_code >= 400:
            return AgentResult(
                success=False,
                error=f"opencode prompt failed ({resp.status_code}): {resp.text[:500]}",
            )
        data = resp.json() if resp.content else {}

    usage: AgentUsage | None = None
    output = ""
    if isinstance(data, dict):
        output = str(
            data.get("result") or data.get("text") or data.get("output") or json.dumps(data)[:2000]
        )
        # Best-effort usage extraction
        info = data.get("info") or data.get("usage") or {}
        if isinstance(info, dict):
            inp = int(info.get("input_tokens") or info.get("input") or 0)
            out = int(info.get("output_tokens") or info.get("output") or 0)
            cache_read = resolve_cache_read(info)
            cost = info.get("cost") or info.get("costUsd")
            if inp or out or cost:
                usage = AgentUsage(
                    agent="opencode",
                    input_tokens=inp + cache_read.additive,
                    output_tokens=out,
                    cache_read_tokens=cache_read.reported or None,
                    cost_usd=float(cost) if cost is not None else None,
                )
                log_token_table(
                    input_tokens=inp,
                    cache_read=0,
                    cache_write=0,
                    output=out,
                    cost_usd=usage.cost_usd,
                )
    return AgentResult(success=True, output=output or None, usage=usage)


async def _run(ctx: AgentRunContext) -> AgentResult:
    try:
        cli = await _install(None)
    except FileNotFoundError as err:
        return AgentResult(success=False, error=str(err))

    model = ctx.resolved_model
    config_json = build_security_config(ctx, model)
    config_path = Path(ctx.tmpdir) / "opencode.json"
    config_path.write_text(config_json, encoding="utf-8")
    extras: dict[str, str] = {
        "OPENCODE_CONFIG_CONTENT": config_json,
        "OPENCODE_CONFIG": str(config_path),
    }
    model_s = (model or "").strip()
    bedrock_id = os.environ.get("BEDROCK_MODEL_ID", "").strip()
    vertex_id = os.environ.get("VERTEX_MODEL_ID", "").strip()
    if bedrock_id and model_s == bedrock_id:
        extras["CLAUDE_CODE_USE_BEDROCK"] = "1"
    if vertex_id and model_s == vertex_id:
        extras["CLAUDE_CODE_USE_VERTEX"] = "1"
    env = build_agent_env("opencode", extras)

    # Prefer serve + HTTP when available; fall back to `opencode run`
    handle: _ServerHandle | None = None
    try:
        handle = _boot_opencode_server(cli=cli, env=env, cwd=os.getcwd())
    except Exception as err:
        logger.info("opencode serve unavailable ({}), falling back to run", err)
        return await _run_cli_fallback(cli=cli, ctx=ctx, env=env)

    assert handle is not None
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
                return AgentResult(
                    success=False,
                    error=f"failed to create opencode session: {created.text[:300]}",
                )
            session = created.json()
            session_id = str(session.get("id") or session.get("sessionID") or "")
            if not session_id:
                return AgentResult(success=False, error="opencode session missing id")

        model_obj = _parse_model(model)
        system = ctx.instructions.system
        user = ctx.instructions.user
        prompt = f"{system}\n\n{user}".strip() if system else user

        # OB3 — the trust tier is ``derive_trust_tier()``'s output carried on
        # the tool state, never an env fallback (D7 — the untrusted content
        # cap must not be defeatable by environment control).
        capture_policy = resolve_capture_policy(ctx.tool_state.trust_tier)

        initial = await _prompt_session(
            base_url=handle.base_url,
            session_id=session_id,
            text=prompt,
            model=model_obj,
            resolved_model=model,
            capture_policy=capture_policy,
        )

        async def resume(followup: str) -> AgentResult:
            return await _prompt_session(
                base_url=handle.base_url,
                session_id=session_id,
                text=followup,
                model=model_obj,
                resolved_model=model,
                capture_policy=capture_policy,
            )

        try:
            result = await run_post_run_retry_loop(ctx, initial=initial, resume=resume)
        except ProviderTimeoutError as exc:
            # Controlled domain error: surface as a clean failed attempt
            # rather than letting a raw httpx traceback abort the review.
            return AgentResult(success=False, error=str(exc))
        return await finalize_agent_result(ctx, result)
    finally:
        handle.close()


async def _run_cli_fallback(*, cli: str, ctx: AgentRunContext, env: dict[str, str]) -> AgentResult:
    prompt = ctx.instructions.user
    if ctx.instructions.system:
        prompt = f"{ctx.instructions.system}\n\n{prompt}"
    cmd = [cli, "run", "--format", "json", prompt]
    if ctx.resolved_model:
        cmd.extend(["--model", ctx.resolved_model])
    # W6 migration: opencode ``--format json`` may emit multiple NDJSON
    # events. We attempt the streaming read loop and fall back to the
    # legacy last-line parse if the events are not granular enough (D12).
    # Run-level spans are emitted through the W4 tracer regardless.
    # Blocking Popen/wait runs in a worker thread so outer wait_for can preempt.
    return await asyncio.to_thread(
        _run_opencode_cli_streaming,
        cmd=cmd,
        ctx=ctx,
        env=env,
    )


def _run_opencode_cli_streaming(
    *,
    cmd: list[str],
    ctx: AgentRunContext,
    env: dict[str, str],
) -> AgentResult:
    """Streaming read loop for ``opencode run --format json`` (W6).

    Opencode's JSON output is **partial** (W0.5) — events may not be
    granular enough for per-tool spans. We attempt the streaming read
    and degrade to run-level spans if the events lack the required
    fields (D12).
    """
    from mergecraft.agents._stream_consumer import (
        StreamSpanAccumulator,
        consume_stream,
    )
    from mergecraft.tracing.sinks import claim_sink

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

    try:
        process = spawn_agent_cli(cmd, env=env)
    except FileNotFoundError as err:
        return AgentResult(success=False, error=str(err))

    assert process.stdout is not None
    assert process.stderr is not None

    stderr_text = ""
    returncode: int = -1
    try:
        with track_process_group(process):
            try:
                # Opencode events are partial: try streaming, but the
                # handler is a no-op for unknown shapes (graceful degradation).
                consume_stream(
                    raw_stream=process.stdout,
                    accumulator=accumulator,
                    handler=lambda _acc, _event: None,
                )
                stderr_text = process.stderr.read() or ""
                returncode = wait_or_kill_process_group(
                    process,
                    timeout=int(os.environ.get("MERGECRAFT_AGENT_TIMEOUT", "3600")),
                )
            except subprocess.TimeoutExpired:
                return AgentResult(success=False, error="opencode run timed out")
    finally:
        pass

    if returncode != 0:
        retryable = is_retryable_cli_failure(returncode=returncode, stderr=stderr_text)
        return AgentResult(
            success=False,
            error=(stderr_text or "opencode failed").strip() or f"opencode exited {returncode}",
            metadata={"retryable": True} if retryable else {},
        )
    return AgentResult(success=True, output=accumulator.final_output or None)


opencode = agent(name="opencode", install=_install, run=_run, module_file=__file__)
