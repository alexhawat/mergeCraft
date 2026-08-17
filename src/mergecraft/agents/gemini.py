"""Gemini CLI agent harness — invokes ``gemini`` with MCP settings."""

from __future__ import annotations

import asyncio
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
    spawn_agent_cli,
)
from mergecraft.agents.verifier import VERIFIER_AGENT_NAME, VERIFIER_SYSTEM_PROMPT
from mergecraft.tracing._tool_attrs import (
    emit_verb_subevent,
    enrich_tool_request,
    enrich_tool_response,
)
from mergecraft.tracing.genai import output_messages_attrs, resolve_capture_policy
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

GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
GOOGLE_GENERATIVE_AI_API_KEY_ENV = "GOOGLE_GENERATIVE_AI_API_KEY"


def _strip_provider_prefix(specifier: str) -> str:
    slash = specifier.find("/")
    return specifier[slash + 1 :] if slash > 0 else specifier


def _gemini_home(ctx: AgentRunContext) -> Path:
    return Path(ctx.tmpdir) / ".gemini"


def _build_subagent_instructions(subagent_block: str | None = None) -> str:
    if subagent_block is not None:
        return subagent_block
    return "\n\n".join(
        [
            "Registered read-only subagents (spawn when needed):",
            f"## {REVIEWER_AGENT_NAME}",
            REVIEWER_SYSTEM_PROMPT,
            f"## {VERIFIER_AGENT_NAME}",
            VERIFIER_SYSTEM_PROMPT,
        ]
    )


def _build_instruction_text(ctx: AgentRunContext, *, subagent_block: str | None = None) -> str:
    instructions_parts: list[str] = []
    if ctx.instructions.system:
        instructions_parts.append(ctx.instructions.system)
    instructions_parts.append(_build_subagent_instructions(subagent_block))
    return "\n\n".join(instructions_parts)


def _build_gemini_prompt(ctx: AgentRunContext, prompt: str) -> str:
    sections = [_build_instruction_text(ctx)]
    user = (prompt or ctx.instructions.user or "").strip()
    if user:
        sections.append(user)
    return "\n\n".join(sections)


def write_mcp_config(
    ctx: AgentRunContext,
    *,
    subagent_block: str | None = None,
) -> str:
    """Write Gemini ``settings.json`` under the run temp dir and return its path."""
    gemini_home = _gemini_home(ctx)
    gemini_home.mkdir(parents=True, exist_ok=True)
    instructions_path = gemini_home / "GEMINI.md"
    instructions_path.write_text(
        _build_instruction_text(ctx, subagent_block=subagent_block),
        encoding="utf-8",
    )

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
    # write_mcp_config runs in the root orchestrator, before the privilege
    # drop wraps the actual gemini subprocess in setpriv — a plain mkdir()
    # here creates gemini_home owned by root regardless of its parent's
    # permissions, so the dropped-to agent user cannot write under it later
    # (same bug class as codex.py's $CODEX_HOME).
    from mergecraft.utils.privilege import prepare_workspace_for_agent

    prepare_workspace_for_agent(str(gemini_home))
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
    env = build_agent_env("gemini", {"HOME": str(Path(ctx.tmpdir))})
    _normalize_gemini_api_key(env)
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

    # OB3 — see codex: the trust tier is ``derive_trust_tier()``'s output
    # from the tool state, never an env fallback (D7).
    capture_policy = (
        resolve_capture_policy(ctx.tool_state.trust_tier) if tracer is not None else None
    )
    handler, close_all_open_spans = _gemini_stream_event_handler(
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
        retryable = is_retryable_cli_failure(returncode=returncode, stderr=stderr_text)
        return AgentResult(
            success=False,
            output=output or None,
            error=stderr_text.strip() or f"gemini exited {returncode}",
            usage=usage,
            metadata={"retryable": True} if retryable else {},
        )
    return AgentResult(success=True, output=output or None, usage=usage)


def _gemini_stream_event_handler(
    *,
    tracer: Tracer | None,
    model_id: str,
    capture_policy: ContentCapture | None = None,
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
                # T2 / D10 — ``provider.call`` is a real span kind, not an
                # attr. Opens on ``init`` and closes on the terminal
                # ``result`` / ``error`` event; the ``llm.call`` span
                # becomes its child so Logfire groups every Gemini
                # chat-completions request under one row. W5 / H1 — open
                # via the shared pair helper so the provider + llm attrs
                # + ``__enter__`` are applied atomically; the resulting
                # ``ProviderLLMPair`` is the single state unit per attempt.
                pair = _open_provider_llm_pair(
                    tracer,
                    model_id=model_id,
                    family="chat_completions",
                    provider_id="google_gemini",
                )
                if pair is not None:
                    # W6 / L3 — ``_open_provider_llm_pair`` already stamps
                    # ``model.id`` on the parent ``provider.call`` span (the
                    # canonical home per the helper docstring). The llm span
                    # inherits the value through the OTel/mergeCraft parent
                    # chain; do not re-stamp here.
                    pair.llm.set_attribute("model.event", "init")
                    pair.llm.set_attribute("gen_ai.system", "google")
                    pair.llm.set_attribute("gen_ai.operation.name", "chat")
                    pair.llm.set_attribute("gen_ai.request.model", model_id)
                    pair.llm.set_attribute("gen_ai.response.model", model_id)
                open_pairs["default"] = pair
                open_pair_bookkeeping["default"] = {"tokens_in": 0, "tokens_out": 0}
            return

        if event_type == "message":
            content = event.get("content")
            role = event.get("role")
            if role == "assistant" and isinstance(content, str) and content:
                accumulator.set_output(content)
                # O5 (OB3) — the assistant message text is the completion
                # payload; capture it on the open llm span under the content
                # policy. ``capture_policy=None`` keeps the pre-OB3 surface.
                if capture_policy is not None:
                    pair = open_pairs.get("default")
                    if pair is not None:
                        for attr_key, attr_value in output_messages_attrs(
                            [{"role": "assistant", "content": content}],
                            policy=capture_policy,
                        ).items():
                            pair.llm.set_attribute(attr_key, attr_value)
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
                span.set_attribute("gen_ai.operation.name", "execute_tool")
                span.set_attribute("gen_ai.tool.name", tool_name)
                span.set_attribute("gen_ai.tool.call.id", tool_id)
                tool_input = event.get("input")
                if tool_input is not None:
                    # T1 / D5 / W4 — request-side enrichment via the shared helper.
                    enrich_tool_request(span, arguments=tool_input)
                    span.set_attribute("tool.input", tool_input)
                    span.set_attribute("gen_ai.tool.input", redact_tool_payload(tool_input))
                open_tool_spans[tool_id] = {"span": span, "name": tool_name}
            return

        if event_type == "tool_result":
            tool_id = str(event.get("tool_use_id") or "")
            entry = open_tool_spans.pop(tool_id, None)
            if entry is None:
                return
            span_obj = entry.get("span")
            if span_obj is not None:
                tool_output = str(event.get("output") or "")
                # T1 / D5 / W4 — response-side enrichment via the shared helper.
                enrich_tool_response(span_obj, output=tool_output)
                span_obj.set_attribute("tool.output", tool_output)
                span_obj.set_attribute("gen_ai.tool.output", redact_tool_payload(tool_output))
                # W4 / M6 — ``Span.close`` owns end-time + active-context reset.
                span_obj.close()
                # T1 / D5 — known-verb tools also emit a verb-specific
                # child span (tool.browse for ``browser``, etc.) for
                # finer-grained Logfire grouping. Fire-and-forget; no new
                # bookkeeping state.
                emit_verb_subevent(
                    tracer,
                    parent_span_id=span_obj.span_id,
                    tool_name=entry.get("name", "unknown"),
                    attrs=dict(span_obj._attrs),
                )
            return

        if event_type == "result":
            usage = event.get("usage") if isinstance(event.get("usage"), dict) else None
            if usage is not None:
                accumulator.replace_usage(usage)
            response = event.get("response")
            if isinstance(response, str) and response:
                accumulator.set_output(response)
            # W5 / H1 / M2 — one ``ProviderLLMPair`` per attempt owns the
            # close discipline. Stamp cost + usage attrs on the inner llm
            # span before closing so the per-message totals land on the row.
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
            for key in list(open_pairs.keys()):
                _close_provider_llm_pair(open_pairs.pop(key))
            open_pair_bookkeeping.clear()
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
                    span_obj.close()
            open_tool_spans.clear()
            # W5 / H1 / M2 — one ``ProviderLLMPair`` per attempt; close
            # via the shared helper to preserve the LIFO discipline.
            for key in list(open_pairs.keys()):
                _close_provider_llm_pair(open_pairs.pop(key))
            open_pair_bookkeeping.clear()
            return

    def close_all() -> None:
        for entry in list(open_tool_spans.values()):
            span_obj = entry.get("span")
            if span_obj is not None:
                span_obj.ts_end_ns = time.time_ns()
                span_obj.__exit__(None, None, None)
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

    render_result = render_for_run(ctx, "gemini")
    subagent_block = render_result.payload if isinstance(render_result.payload, str) else None
    write_mcp_config(ctx, subagent_block=subagent_block)
    # Blocking Popen/wait/stream consume runs in a worker thread so
    # ``asyncio.wait_for`` in ``main`` can preempt the coroutine (W9.2).
    initial = await asyncio.to_thread(
        _run_gemini_once,
        cli=cli,
        prompt=ctx.instructions.user,
        ctx=ctx,
        mcp_config="",
    )

    async def resume(prompt: str) -> AgentResult:
        return await asyncio.to_thread(
            _run_gemini_once,
            cli=cli,
            prompt=prompt,
            ctx=ctx,
            mcp_config="",
            continue_session=True,
        )

    result = await run_post_run_retry_loop(ctx, initial=initial, resume=resume)
    finalized = await finalize_agent_result(ctx, result)
    return merge_manifest_metadata(finalized, render_result)


gemini = agent(name="gemini", install=_install, run=_run, build_env=_build_env)
