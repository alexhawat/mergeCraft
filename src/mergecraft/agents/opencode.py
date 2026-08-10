"""OpenCode agent harness — invokes `opencode` CLI / serve."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import httpx
from loguru import logger

from mergecraft.agents.gates import build_opencode_native_fs_permission
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

CUSTOM_PROVIDER_BASE_URL_ENV = "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL"
CUSTOM_PROVIDER_API_KEY_ENV = "MERGECRAFT_CUSTOM_PROVIDER_API_KEY"


def build_custom_provider(model: str | None) -> dict[str, object] | None:
    """Describe an OpenAI-compatible provider declared through the environment.

    The provider id is the segment of ``model`` before the first slash, so
    ``nous/deepseek/deepseek-v4-flash`` registers provider ``nous`` serving model
    ``deepseek/deepseek-v4-flash``. Returns ``None`` unless both the base URL and
    the API key are set, since opencode cannot authenticate with either alone.
    """
    base_url = os.environ.get(CUSTOM_PROVIDER_BASE_URL_ENV, "").strip()
    api_key = os.environ.get(CUSTOM_PROVIDER_API_KEY_ENV, "").strip()
    if not (base_url and api_key and model):
        return None
    slash = model.find("/")
    if slash <= 0:
        return None
    provider_id, model_id = model[:slash].lower(), model[slash + 1 :]
    return {
        provider_id: {
            "npm": "@ai-sdk/openai-compatible",
            "name": provider_id,
            "options": {"baseURL": base_url, "apiKey": api_key},
            "models": {model_id: {"name": model_id}},
        }
    }


def build_security_config(ctx: AgentRunContext, model: str | None) -> str:
    fs_perm = build_opencode_native_fs_permission()
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
            }
        },
        "agent": {
            REVIEWER_AGENT_NAME: {
                "description": ("Read-only review subagent for lens-based code review."),
                "prompt": REVIEWER_SYSTEM_PROMPT,
                "mode": "subagent",
            },
            VERIFIER_AGENT_NAME: {
                "description": (
                    "Read-only verification subagent for Critical/Major analyzer findings."
                ),
                "prompt": VERIFIER_SYSTEM_PROMPT,
                "mode": "subagent",
            },
        },
    }
    if model:
        config["model"] = model
        slash = model.find("/")
        if slash > 0:
            config["enabled_providers"] = [model[:slash].lower()]
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
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def _boot_opencode_server(*, cli: str, env: dict[str, str], cwd: str) -> _ServerHandle:
    proc = subprocess.Popen(
        [cli, "serve", "--port", "0", "--hostname", "127.0.0.1"],
        cwd=cwd,
        env=env,
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
        proc.kill()
        msg = "opencode serve did not print a listening URL"
        raise RuntimeError(msg)
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
) -> AgentResult:
    payload: dict[str, object] = {
        "parts": [{"type": "text", "text": text}],
    }
    if model:
        payload["model"] = model
    async with httpx.AsyncClient(timeout=600.0) as client:
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
            cost = info.get("cost") or info.get("costUsd")
            if inp or out or cost:
                usage = AgentUsage(
                    agent="opencode",
                    input_tokens=inp,
                    output_tokens=out,
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
    env = dict(os.environ)
    env["OPENCODE_CONFIG_CONTENT"] = config_json
    # Also write a config file for CLIs that prefer files
    config_path = Path(ctx.tmpdir) / "opencode.json"
    config_path.write_text(config_json, encoding="utf-8")
    env["OPENCODE_CONFIG"] = str(config_path)

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

        initial = await _prompt_session(
            base_url=handle.base_url,
            session_id=session_id,
            text=prompt,
            model=model_obj,
        )

        async def resume(followup: str) -> AgentResult:
            return await _prompt_session(
                base_url=handle.base_url,
                session_id=session_id,
                text=followup,
                model=model_obj,
            )

        result = await run_post_run_retry_loop(ctx, initial=initial, resume=resume)
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
    return _run_opencode_cli_streaming(
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
    from mergecraft.tracing.tracer import (
        Tracer,
        resolve_correlation_from_env,
        resolve_session_id,
    )

    accumulator = StreamSpanAccumulator(agent_name="opencode")
    try:
        from mergecraft.config import RepoSettings

        sink = claim_sink(RepoSettings().tracing)
        if sink is not None:
            correlation = resolve_correlation_from_env()
            session_id = resolve_session_id()
            run_id = str(correlation.get("run_id") or session_id)
            Tracer(sink=sink, session_id=session_id, run_id=run_id)
    except Exception as exc:
        logger.debug("opencode stream tracer resolution failed: {}", exc)

    try:
        process = subprocess.Popen(
            cmd,
            cwd=os.getcwd(),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as err:
        return AgentResult(success=False, error=str(err))

    assert process.stdout is not None
    assert process.stderr is not None

    stderr_text = ""
    try:
        try:
            # Opencode events are partial: try streaming, but the
            # handler is a no-op for unknown shapes (graceful degradation).
            consume_stream(
                raw_stream=process.stdout,
                accumulator=accumulator,
                handler=lambda _acc, _event: None,
            )
            stderr_text = process.stderr.read() or ""
            returncode = process.wait(
                timeout=int(os.environ.get("MERGECRAFT_AGENT_TIMEOUT", "3600"))
            )
        except subprocess.TimeoutExpired:
            process.kill()
            return AgentResult(success=False, error="opencode run timed out")
    finally:
        pass

    if returncode != 0:
        return AgentResult(
            success=False,
            error=(stderr_text or "opencode failed").strip() or f"opencode exited {returncode}",
        )
    return AgentResult(success=True, output=accumulator.final_output or None)


opencode = agent(name="opencode", install=_install, run=_run)
