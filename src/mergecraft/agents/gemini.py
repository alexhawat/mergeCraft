"""Gemini CLI agent harness — invokes ``gemini`` with MCP settings."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from collections.abc import Callable

    from mergecraft.agents._stream_consumer import StreamSpanAccumulator
    from mergecraft.tracing.tracer import Tracer

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


def _build_instruction_text(ctx: AgentRunContext) -> str:
    instructions_parts: list[str] = []
    if ctx.instructions.system:
        instructions_parts.append(ctx.instructions.system)
    instructions_parts.append(_build_subagent_instructions())
    return "\n\n".join(instructions_parts)


def _build_gemini_prompt(ctx: AgentRunContext, prompt: str) -> str:
    sections = [_build_instruction_text(ctx)]
    user = (prompt or ctx.instructions.user or "").strip()
    if user:
        sections.append(user)
    return "\n\n".join(sections)


def write_mcp_config(ctx: AgentRunContext) -> str:
    """Write Gemini ``settings.json`` under the run temp dir and return its path."""
    gemini_home = _gemini_home(ctx)
    gemini_home.mkdir(parents=True, exist_ok=True)
    instructions_path = gemini_home / "GEMINI.md"
    instructions_path.write_text(_build_instruction_text(ctx), encoding="utf-8")

    server_config: dict[str, object] = {
        "httpUrl": ctx.mcp_server_url,
        "trust": True,
    }
    excluded_tools = [str(name) for name in ctx.subagent_denied_tools]
    if excluded_tools:
        server_config["excludeTools"] = excluded_tools

    settings = {
        "mcpServers": {
            MERGECRAFT_MCP_NAME: server_config,
        },
        "context": {
            "fileName": "GEMINI.md",
        },
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

    user_prompt = _build_gemini_prompt(ctx, prompt)
    cmd = [
        cli,
        "-p",
        user_prompt,
        "--output-format",
        "stream-json",
    ]
    if model:
        cmd.extend(["-m", model])
    if continue_session:
        cmd.extend(["--resume", "latest"])
    if os.environ.get("CI") == "true":
        cmd.append("-y")

    logger.info("invoking gemini CLI (model={})", model or "default")

    # W6 migration: switch to ``subprocess.Popen`` and consume the
    # ``stream-json`` output through ``consume_stream`` so per-event
    # ``tool.call`` / ``llm.call`` spans are emitted via the W4 tracer.
    return _run_gemini_streaming(
        cmd=cmd,
        ctx=ctx,
        model=model,
    )


def _run_gemini_streaming(
    *,
    cmd: list[str],
    ctx: AgentRunContext,
    model: str | None,
) -> AgentResult:
    """Streaming read loop for ``gemini --output-format stream-json`` (W6)."""
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

    accumulator = StreamSpanAccumulator(agent_name="gemini")
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
        logger.debug("gemini stream tracer resolution failed: {}", exc)

    handler, close_all_open_spans = _gemini_stream_event_handler(
        tracer=tracer,
        model_id=model or "default",
    )

    try:
        process = subprocess.Popen(
            cmd,
            cwd=os.getcwd(),
            env=_build_env(ctx),
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
            consume_stream(
                raw_stream=process.stdout,
                accumulator=accumulator,
                handler=handler,
            )
            stderr_text = process.stderr.read() or ""
            returncode = process.wait(
                timeout=int(os.environ.get("MERGECRAFT_AGENT_TIMEOUT", "3600"))
            )
        except subprocess.TimeoutExpired:
            process.kill()
            return AgentResult(success=False, error="gemini CLI timed out")
    finally:
        try:
            close_all_open_spans()
        except Exception as exc:
            logger.debug("gemini stream handler cleanup failed: {}", exc)

    if stderr_text.strip():
        for line in stderr_text.strip().splitlines()[-20:]:
            logger.debug("[gemini] {}", line)

    output = accumulator.final_output
    usage = accumulator.to_usage()

    if returncode != 0:
        return AgentResult(
            success=False,
            output=output or None,
            error=stderr_text.strip() or f"gemini exited {returncode}",
            usage=usage,
        )
    return AgentResult(success=True, output=output or None, usage=usage)


def _gemini_stream_event_handler(
    *,
    tracer: Tracer | None,
    model_id: str,
) -> tuple[
    Callable[[StreamSpanAccumulator, dict[str, Any]], None],
    Callable[[], None],
]:
    """Build a ``consume_stream`` handler for gemini ``stream-json`` events (W6).

    Gemini emits a sequence of NDJSON events with a ``type`` field:
    ``init``, ``message`` (with optional ``role``), ``tool_use``,
    ``tool_result``, ``error``, ``result``. Each event drives a span
    emission through ``consume_stream``; the resulting ``AgentUsage``
    matches the legacy last-line parser.
    """
    open_tool_spans: dict[str, dict[str, Any]] = {}
    open_llm_spans: dict[str, dict[str, Any]] = {}

    def handler(
        accumulator: StreamSpanAccumulator,
        event: dict[str, Any],
    ) -> None:
        event_type = str(event.get("type") or "")

        # Legacy single-blob shape — a final result JSON with no ``type``
        # field. The pre-streaming parser used ``_parse_gemini_payload`` to
        # extract ``result`` / ``output`` / ``response`` and ``usage``;
        # replay that shape here so the equivalence contract holds for
        # older Gemini CLI builds or test fixtures.
        if not event_type:
            output, usage = _parse_gemini_payload(event)
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

        if event_type == "init":
            if tracer is not None:
                span = tracer.start_span("llm.call")
                span.__enter__()
                span.set_attribute("model.id", model_id)
                span.set_attribute("model.event", "init")
                open_llm_spans["default"] = {
                    "span": span,
                    "tokens_in": 0,
                    "tokens_out": 0,
                }
            return

        if event_type == "message":
            content = event.get("content")
            role = event.get("role")
            if role == "assistant" and isinstance(content, str) and content:
                accumulator.set_output(content)
            return

        if event_type == "tool_use":
            tool_id = str(event.get("id") or "")
            tool_name = str(event.get("name") or "unknown")
            if not tool_id:
                return
            if tool_id in open_tool_spans:
                return
            if tracer is not None:
                span = tracer.start_span("tool.call")
                span.__enter__()
                span.set_attribute("tool.id", tool_id)
                span.set_attribute("tool.name", tool_name)
                span.set_attribute("tool.server", "gemini")
                open_tool_spans[tool_id] = {"span": span, "name": tool_name}
            return

        if event_type == "tool_result":
            tool_id = str(event.get("tool_use_id") or "")
            entry = open_tool_spans.pop(tool_id, None)
            if entry is None:
                return
            span_obj = entry.get("span")
            if span_obj is not None:
                span_obj.set_attribute("tool.output", str(event.get("output") or ""))
                span_obj.ts_end_ns = time.time_ns()
                span_obj.__exit__(None, None, None)
            return

        if event_type == "result":
            usage = event.get("usage") if isinstance(event.get("usage"), dict) else None
            if usage is not None:
                accumulator.replace_usage(usage)
            response = event.get("response")
            if isinstance(response, str) and response:
                accumulator.set_output(response)
            for entry in list(open_llm_spans.values()):
                span_obj = entry.get("span")
                if span_obj is not None:
                    span_obj.set_attribute("cost.tokens_in", entry["tokens_in"])
                    span_obj.set_attribute("cost.tokens_out", entry["tokens_out"])
                    span_obj.ts_end_ns = time.time_ns()
                    span_obj.__exit__(None, None, None)
            open_llm_spans.clear()
            return

        if event_type == "error":
            # surface the error message into the accumulator's output so
            # callers see the failure context, then close any open spans
            err = event.get("message")
            if isinstance(err, str):
                accumulator.set_output(err)
            for entry in list(open_tool_spans.values()):
                span_obj = entry.get("span")
                if span_obj is not None:
                    span_obj.ts_end_ns = time.time_ns()
                    span_obj.__exit__(None, None, None)
            open_tool_spans.clear()
            for entry in list(open_llm_spans.values()):
                span_obj = entry.get("span")
                if span_obj is not None:
                    span_obj.ts_end_ns = time.time_ns()
                    span_obj.__exit__(None, None, None)
            open_llm_spans.clear()
            return

    def close_all() -> None:
        for entry in list(open_tool_spans.values()):
            span_obj = entry.get("span")
            if span_obj is not None:
                span_obj.ts_end_ns = time.time_ns()
                span_obj.__exit__(None, None, None)
        open_tool_spans.clear()
        for entry in list(open_llm_spans.values()):
            span_obj = entry.get("span")
            if span_obj is not None:
                span_obj.ts_end_ns = time.time_ns()
                span_obj.__exit__(None, None, None)
        open_llm_spans.clear()

    return handler, close_all


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
