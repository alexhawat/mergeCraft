"""Claude Code agent harness — invokes `claude` CLI with MCP config JSON.

Reads ``claude`` stdout as an incremental NDJSON stream (``stream-json``
output format) so per-tool-call and per-message spans can be emitted
during the run rather than after a full-buffer parse. Falls back to a
legacy last-line-JSON parse when the streaming read returns no events.
"""

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

from mergecraft.agents._stream_consumer import StreamSpanAccumulator, consume_stream
from mergecraft.agents._tool_attrs import emit_verb_subevent, enrich_tool_call_attrs
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
from mergecraft.agents.verifier import (
    VERIFIER_AGENT_NAME,
    VERIFIER_RUBRIC_VERSION,
    VERIFIER_SYSTEM_PROMPT,
    pinned_judge_model,
)
from mergecraft.tracing.sinks import claim_sink
from mergecraft.types import MERGECRAFT_MCP_NAME
from mergecraft.utils.privilege import wrap_agent_command
from mergecraft.utils.process_group import track_process_group, wait_or_kill_process_group
from mergecraft.utils.retry_policy import is_retryable_cli_failure
from mergecraft.utils.secrets import build_agent_env

if TYPE_CHECKING:
    from collections.abc import Callable

    from mergecraft.tracing.tracer import Span, Tracer

CLAUDE_EXEC_TOOLS = ("Bash", "Monitor", "REPL", "Workflow")
CLAUDE_EXEC_TOOL_DENY_RULES = [
    *CLAUDE_EXEC_TOOLS,
    *[f"Agent({t})" for t in CLAUDE_EXEC_TOOLS],
]
CLAUDE_DISALLOWED_TOOLS = ",".join(CLAUDE_EXEC_TOOL_DENY_RULES)


def _strip_provider_prefix(specifier: str) -> str:
    slash = specifier.find("/")
    return specifier[slash + 1 :] if slash > 0 else specifier


def write_mcp_config(ctx: AgentRunContext) -> str:
    config_dir = Path(ctx.tmpdir) / ".claude"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    MERGECRAFT_MCP_NAME: {"type": "http", "url": ctx.mcp_server_url},
                }
            }
        ),
        encoding="utf-8",
    )
    return str(config_path)


def build_agents_json() -> str:
    agents = {
        REVIEWER_AGENT_NAME: {
            "description": (
                "Read-only review subagent for lens-based code review. "
                "Reads only — no writes, no state-changing shell or MCP calls."
            ),
            "prompt": REVIEWER_SYSTEM_PROMPT,
            "model": "claude-sonnet-5",
        },
        VERIFIER_AGENT_NAME: {
            "description": (
                "Read-only verification subagent for Critical/Major analyzer, CI and "
                "agent-authored findings. Confirms, downgrades, or drops before "
                f"publication against rubric v{VERIFIER_RUBRIC_VERSION}."
            ),
            "prompt": VERIFIER_SYSTEM_PROMPT,
            # Pinned in agents/verifier.py so the judge model recorded with a
            # verdict and the judge model actually dispatched cannot diverge
            # (#45). Sonnet is deliberately a different tier from the
            # orchestrator that wrote the finding.
            "model": pinned_judge_model("claude") or "claude-sonnet-5",
        },
    }
    return json.dumps(agents)


async def _install(_token: str | None = None) -> str:
    path = shutil.which("claude")
    if path:
        return path
    # Prefer locally installed package binary if present
    local = Path(ctx_tmpdir_fallback()) / "node_modules" / ".bin" / "claude"
    if local.exists():
        return str(local)
    msg = (
        "claude CLI not found on PATH. Install @anthropic-ai/claude-code "
        "or ensure `claude` is available."
    )
    raise FileNotFoundError(msg)


def ctx_tmpdir_fallback() -> str:
    return os.environ.get("MERGECRAFT_TEMP_DIR") or "/tmp"


_STDERR_TAIL_LINES = 20


def _claude_attempt_context(*, model: str | None, skip_permissions: bool) -> str:
    parts = [f"model={model or 'default'}"]
    if skip_permissions:
        parts.append("--dangerously-skip-permissions")
    if os.environ.get("CI") == "true":
        parts.append("CI=true")
    return ", ".join(parts)


def _build_claude_failure_error(
    *,
    returncode: int,
    stderr: str,
    model: str | None,
    skip_permissions: bool,
) -> str:
    context = _claude_attempt_context(model=model, skip_permissions=skip_permissions)
    stderr_lines = [line for line in (stderr or "").strip().splitlines() if line.strip()]
    if stderr_lines:
        tail = stderr_lines[-_STDERR_TAIL_LINES:]
        stderr_part = "; stderr tail: " + " | ".join(tail)
    else:
        stderr_part = " (no stderr output)"
    return f"claude exited {returncode} ({context}){stderr_part}"


def _build_env(ctx: AgentRunContext) -> dict[str, str]:
    extras: dict[str, str] = {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
    model = (ctx.resolved_model or "").strip()
    bedrock_id = os.environ.get("BEDROCK_MODEL_ID", "").strip()
    vertex_id = os.environ.get("VERTEX_MODEL_ID", "").strip()
    lowered = model.lower()
    if (
        "bedrock" in lowered
        or os.environ.get("CLAUDE_CODE_USE_BEDROCK", "").strip()
        or (bedrock_id and model == bedrock_id)
    ):
        extras["CLAUDE_CODE_USE_BEDROCK"] = "1"
    if (
        "vertex" in lowered
        or os.environ.get("CLAUDE_CODE_USE_VERTEX", "").strip()
        or (vertex_id and model == vertex_id)
    ):
        extras["CLAUDE_CODE_USE_VERTEX"] = "1"
    return build_agent_env("claude", extras)


def _build_claude_streaming_usage(payload: dict[str, Any]) -> AgentUsage:
    """Render one ``usage`` payload as an ``AgentUsage``.

    Mirrors the legacy blob-parser output so the post-migration
    ``AgentResult.usage`` matches what the W5.7 equivalence test pins.
    """
    usage_raw = payload.get("usage") or {}
    input_tokens = int(usage_raw.get("input_tokens") or usage_raw.get("inputTokens") or 0)
    output_tokens = int(usage_raw.get("output_tokens") or usage_raw.get("outputTokens") or 0)
    cache_read = int(
        usage_raw.get("cache_read_input_tokens") or usage_raw.get("cacheReadTokens") or 0
    )
    cache_write = int(
        usage_raw.get("cache_creation_input_tokens") or usage_raw.get("cacheWriteTokens") or 0
    )
    cost = payload.get("total_cost_usd")
    return AgentUsage(
        agent="claude",
        input_tokens=input_tokens + cache_read + cache_write,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read or None,
        cache_write_tokens=cache_write or None,
        cost_usd=float(cost) if cost is not None else None,
    )


def _claude_stream_event_handler(
    *,
    tracer: Tracer | None,
    parent_span_id: str | None,
    model_id: str,
) -> tuple[Any, Callable[[], None]]:
    """Build a per-event handler that emits ``tool.call`` / ``llm.call`` spans.

    The handler tracks in-flight ``llm.call`` spans keyed by ``message.id`` so
    ``message_delta`` events update the same span rather than opening a new
    one. Per-message usage is tracked separately from the run-wide
    accumulator so each ``llm.call`` span's ``cost.*`` attributes reflect the
    per-message tokens, not the running total (W5.2 contract).

    Returns:
        tuple: ``(handler, close_all)`` where ``handler`` is the per-event
        callable and ``close_all`` is a no-arg function that closes any
        still-open spans in LIFO order. ``close_all`` MUST be called after
        ``consume_stream`` returns to avoid leaking ``_ACTIVE_SPAN`` between
        runs (the W5 fixture's event order can close an outer ``llm.call``
        span before an inner ``tool.call`` span, which would otherwise
        leave the tool span as the active span when the next test runs).
    """
    open_llm_spans: dict[str, dict[str, Any]] = {}
    open_tool_spans: dict[str, Any] = {}
    open_provider_spans: dict[str, dict[str, Any]] = {}

    def _handler(accumulator: StreamSpanAccumulator, event: dict[str, Any]) -> None:
        nonlocal open_llm_spans, open_tool_spans, open_provider_spans
        event_type = event.get("type")

        if event_type == "message_start":
            message = event.get("message") or {}
            message_id = str(message.get("id") or "")
            usage_payload = message.get("usage") or {}
            accumulator.absorb_usage(usage_payload)
            if tracer is None:
                # Still track the open-span bookkeeping so message_stop can
                # find and clear it.
                open_llm_spans[message_id] = {
                    "span": None,
                    "tokens_in": int(usage_payload.get("input_tokens") or 0),
                    "tokens_out": int(usage_payload.get("output_tokens") or 0),
                }
                return
            # T2 / D10 — ``provider.call`` is a real span kind, not an attr.
            # It opens on ``message_start`` and closes on ``message_stop``
            # so the Logfire tree groups every Anthropic request under one
            # row with its transport family on it; the ``llm.call`` span
            # emitted below becomes the parent of any
            # ``http.client.request`` row for visibility into the actual
            # wire call.
            provider_span = tracer.start_span(
                "provider.call",
                parent_span_id=parent_span_id,
            )
            provider_span.set_attribute("provider.id", "anthropic")
            provider_span.set_attribute("provider.transport_family", "anthropic")
            provider_span.set_attribute("model.id", model_id)
            provider_span.set_attribute("gen_ai.system", "anthropic")
            provider_span.set_attribute("gen_ai.operation.name", "chat")
            provider_span.ts_start_ns = time.time_ns()
            provider_span.__enter__()
            span = tracer.start_span(
                "llm.call",
                parent_span_id=provider_span.span_id,
            )
            span.set_attribute("model.id", model_id)
            span.set_attribute("model.event", "message_start")
            span.set_attribute(
                "cost.tokens_in",
                int(usage_payload.get("input_tokens") or 0),
            )
            span.set_attribute(
                "cost.tokens_out",
                int(usage_payload.get("output_tokens") or 0),
            )
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.request.model", model_id)
            span.set_attribute("gen_ai.response.model", model_id)
            span.set_attribute(
                "gen_ai.usage.input_tokens", int(usage_payload.get("input_tokens") or 0)
            )
            span.set_attribute(
                "gen_ai.usage.output_tokens", int(usage_payload.get("output_tokens") or 0)
            )
            span.ts_start_ns = time.time_ns()
            span.__enter__()
            open_provider_spans[message_id] = {"span": provider_span}
            open_llm_spans[message_id] = {
                "span": span,
                "tokens_in": int(usage_payload.get("input_tokens") or 0),
                "tokens_out": int(usage_payload.get("output_tokens") or 0),
            }
            return

        if event_type == "message_delta":
            delta = event.get("delta") or {}
            usage_payload = delta.get("usage") or {}
            accumulator.absorb_usage(usage_payload)
            # The claude stream does not always carry the message id on
            # ``message_delta``; find the only open span (the W5 fixture is
            # single-turn-per-delta, multi-turn sessions are still safely
            # updated because each delta updates the latest open span).
            message_id = ""
            for candidate in (
                event.get("message_id"),
                (event.get("message") or {}).get("id")
                if isinstance(event.get("message"), dict)
                else None,
            ):
                if isinstance(candidate, str) and candidate:
                    message_id = candidate
                    break
            target = (
                open_llm_spans.get(message_id)
                if message_id and message_id in open_llm_spans
                else (next(iter(open_llm_spans.values()), None) if open_llm_spans else None)
            )
            if target is None:
                return
            delta_out = int(usage_payload.get("output_tokens") or 0)
            target["tokens_out"] += delta_out
            span_obj: Span | None = target.get("span")
            if span_obj is not None:
                span_obj.set_attribute("cost.tokens_out", target["tokens_out"])
                span_obj.set_attribute("gen_ai.usage.output_tokens", target["tokens_out"])
            return

        if event_type == "message_stop":
            # Close any in-flight llm.call spans. The claude stream does
            # not always carry the message id on stop, so close all open
            # spans — typical shape is one open span at a time. The
            # ``provider.call`` span wraps the ``llm.call`` span (D10) and
            # closes after the inner span closes so the active-span stack
            # unwinds cleanly.
            for entry in list(open_llm_spans.values()):
                span_obj = entry.get("span")
                if span_obj is not None:
                    span_obj.ts_end_ns = time.time_ns()
                    span_obj.__exit__(None, None, None)
            open_llm_spans.clear()
            for entry in list(open_provider_spans.values()):
                span_obj = entry.get("span")
                if span_obj is not None:
                    span_obj.ts_end_ns = time.time_ns()
                    span_obj.__exit__(None, None, None)
            open_provider_spans.clear()
            return

        if event_type == "content_block_start":
            content_block = event.get("content_block") or {}
            if content_block.get("type") != "tool_use":
                return
            tool_id = str(content_block.get("id") or "")
            tool_name = str(content_block.get("name") or "unknown")
            tool_input = content_block.get("input") or {}
            if tracer is None:
                return
            span = tracer.start_span(
                "tool.call",
                parent_span_id=parent_span_id,
            )
            span.set_attribute("tool.name", tool_name)
            span.set_attribute("tool.id", tool_id)
            span.set_attribute("tool.server", "claude")
            span.set_attribute("tool.input", tool_input)
            span.set_attribute("gen_ai.operation.name", "execute_tool")
            span.set_attribute("gen_ai.tool.name", tool_name)
            span.set_attribute("gen_ai.tool.call.id", tool_id)
            # T1 / D5 — request-side enrichment: byte counts + input-key list
            # so Logfire's row inspector surfaces the request shape even when
            # the driver carries the input as a dict (claude always does).
            from mergecraft.tracing.redaction import redact_tool_payload

            enrich_tool_call_attrs(span, arguments=tool_input)
            span.set_attribute("gen_ai.tool.input", redact_tool_payload(tool_input))
            span.ts_start_ns = time.time_ns()
            span.__enter__()
            open_tool_spans[tool_id] = span
            return

        if event_type == "content_block_stop":
            # The claude stream does not always emit a separate tool_result
            # event with the tool_use_id. The W5 fixture does, but older
            # streams may not — closing on content_block_stop is a safe
            # approximation; the tool_result handler below overrides when
            # an explicit tool_result arrives later.
            index = event.get("index")
            if not open_tool_spans:
                return
            # We do not know which tool id maps to which block index, so
            # leave the actual close to the tool_result handler. This is a
            # no-op for the W5 fixture which always carries an explicit
            # tool_result.
            del index
            return

        if event_type == "tool_result":
            tool_use_id = str(event.get("tool_use_id") or "")
            span = open_tool_spans.pop(tool_use_id, None)
            if span is not None:
                output = event.get("content") or ""
                span.ts_end_ns = time.time_ns()
                # T1 / D5 — response-side enrichment: exit_code, byte
                # count, kind label, and the verbatim output for the row.
                enrich_tool_call_attrs(span, output=output, exit_code="ok")
                span.set_attribute("tool.output", output)
                from mergecraft.tracing.redaction import redact_tool_payload

                span.set_attribute("gen_ai.tool.output", redact_tool_payload(output))
                span.__exit__(None, None, None)
                # T1 / D5 — known-verb tools also emit a verb-specific child
                # span (tool.browse for ``browser``, etc.) for finer-grained
                # Logfire grouping. Fire-and-forget; no new bookkeeping.
                tool_name = str(span._attrs.get("tool.name", "unknown"))
                emit_verb_subevent(
                    tracer,
                    parent_span_id=span.span_id,
                    tool_name=tool_name,
                    attrs=dict(span._attrs),
                )
            return

        if event_type == "result":
            payload = event.get("result")
            if isinstance(payload, str):
                accumulator.set_output(payload)
            # The ``result`` event's ``usage`` is the authoritative final
            # total — replacing (not absorbing) avoids double-counting the
            # token usage that ``message_start`` / ``message_delta`` events
            # already folded into the accumulator. W5.7's equivalence test
            # pins this: the streaming ``AgentResult.usage`` must match the
            # legacy blob parser's last-line JSON parse.
            accumulator.replace_usage(event.get("usage") or {})
            cost = event.get("total_cost_usd")
            if isinstance(cost, (int, float)):
                accumulator.cost_usd = float(cost)

    def close_all() -> None:
        """Close any still-open spans in LIFO order.

        The streaming event order does not guarantee LIFO span closure
        (the W5 fixture's ``message_stop`` arrives before ``tool_result``
        for the message that owns the tool call). Calling ``__exit__``
        on the outer span first would reset ``_ACTIVE_SPAN`` to the
        value held before the outer span was entered, which can drop the
        inner span's token from the stack and leak the inner span into
        the next test's context. Closing in LIFO order — last opened,
        first closed — preserves the expected ``_ACTIVE_SPAN`` stack
        discipline and explicitly clears the slot when the run finishes.
        """
        from mergecraft.tracing.tracer import _ACTIVE_SPAN

        # Tool spans are inner-most; close them first.
        for tool_id in list(open_tool_spans.keys()):
            span = open_tool_spans.pop(tool_id)
            if span is not None:
                if span._context_token is not None:
                    span.__exit__(None, None, None)
        # Then llm.call spans, in reverse insertion order.
        for key in list(reversed(list(open_llm_spans.keys()))):
            entry = open_llm_spans.pop(key)
            span = entry.get("span") if isinstance(entry, dict) else None
            if span is not None and span._context_token is not None:
                span.__exit__(None, None, None)
        # T2 / D10 — provider.call spans wrap llm.call spans. Close after
        # the llm.call spans so the active-span stack unwinds inner-to-outer.
        for key in list(reversed(list(open_provider_spans.keys()))):
            entry = open_provider_spans.pop(key)
            span = entry.get("span") if isinstance(entry, dict) else None
            if span is not None and span._context_token is not None:
                span.__exit__(None, None, None)
        # Defensive: the streaming event order can leave ``_ACTIVE_SPAN``
        # pointing at a closed span because individual ``__exit__`` calls
        # popped the wrong ContextVar frame. Clear the slot so the next
        # run starts from a known-clean state.
        active = _ACTIVE_SPAN.get()
        if active is not None and getattr(active, "_context_token", None) is None:
            _ACTIVE_SPAN.set(None)

    return _handler, close_all


def _run_claude_legacy_blob_parse(
    *, stdout: str, model: str | None, skip_permissions: bool, stderr: str, returncode: int
) -> AgentResult:
    """Preserved legacy path: parse the last JSON line and build ``AgentResult``.

    The W5.7 equivalence test pins that the streaming path and the legacy
    blob path produce the same ``AgentResult`` for the same recorded session.
    When the streaming path sees a single ``result`` event on the last line
    (which is the shape the legacy driver always parsed), the two paths
    converge on the same output and usage.
    """
    del skip_permissions  # legacy path did not embed this in the error string
    output = stdout.strip()
    usage: AgentUsage | None = None
    try:
        data = json.loads(stdout.strip().splitlines()[-1]) if stdout.strip() else {}
        if isinstance(data, dict):
            output = str(data.get("result") or data.get("output") or output)
            usage_raw = data.get("usage") or {}
            if usage_raw or data.get("total_cost_usd") is not None:
                input_tokens = int(
                    usage_raw.get("input_tokens") or usage_raw.get("inputTokens") or 0
                )
                output_tokens = int(
                    usage_raw.get("output_tokens") or usage_raw.get("outputTokens") or 0
                )
                cache_read = int(
                    usage_raw.get("cache_read_input_tokens")
                    or usage_raw.get("cacheReadTokens")
                    or 0
                )
                cache_write = int(
                    usage_raw.get("cache_creation_input_tokens")
                    or usage_raw.get("cacheWriteTokens")
                    or 0
                )
                cost = data.get("total_cost_usd")
                usage = AgentUsage(
                    agent="claude",
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
    except json.JSONDecodeError:
        pass

    if returncode != 0:
        context = _claude_attempt_context(model=model, skip_permissions=False)
        logger.warning(
            "claude CLI failed (exit={}, {}); stdout={!r}; stderr={!r}",
            returncode,
            context,
            stdout,
            stderr,
        )
        return AgentResult(
            success=False,
            output=output or None,
            error=_build_claude_failure_error(
                returncode=returncode,
                stderr=stderr,
                model=model,
                skip_permissions=False,
            ),
            usage=usage,
        )
    return AgentResult(success=True, output=output or None, usage=usage)


def _resolve_active_tracer() -> Tracer | None:
    """Resolve the tracer that the calling context has prepared for spans.

    The W6 streaming driver emits ``tool.call`` / ``llm.call`` spans during
    the subprocess read loop. Production callers (Batch B / W4's chain)
    resolve a tracer via ``get_tracer_from_settings`` ahead of time and
    store it on the agent context. The W5 RED suite's
    ``captured_streaming_sink`` fixture pre-resolves a MemorySink-backed
    tracer via ``sink_factory`` and leaves it on ``_PENDING_SINK``; this
    helper claims that pending sink if present, falling back to a fresh
    ``NullTracer`` when tracing is not active (convention 9).
    """
    try:
        from mergecraft.tracing.resolve import resolve_active_tracing

        sink = claim_sink(resolve_active_tracing())
    except Exception:
        return None

    if sink is None:
        return None
    # The MemorySink fixture's wrapping makes ``sink.inner`` a MultiSink;
    # when the sink factory built a real sink, ``sink`` is itself a RedactingSink.
    # Either way, return a Tracer that emits to ``sink``.
    from mergecraft.tracing.tracer import (
        Tracer as _Tracer,
    )
    from mergecraft.tracing.tracer import (
        resolve_correlation_from_env,
        resolve_session_id,
    )

    correlation = resolve_correlation_from_env()
    session_id = resolve_session_id()
    run_id = str(correlation.get("run_id") or session_id)
    return _Tracer(sink=sink, session_id=session_id, run_id=run_id)


def _run_claude_once(
    *,
    cli: str,
    prompt: str,
    ctx: AgentRunContext,
    mcp_config: str,
    continue_session: bool = False,
) -> AgentResult:
    model = None
    if ctx.resolved_model:
        model = _strip_provider_prefix(ctx.resolved_model)
    cmd = [
        cli,
        "--print",
        "--output-format",
        "stream-json",
        "--mcp-config",
        mcp_config,
        "--disallowedTools",
        CLAUDE_DISALLOWED_TOOLS,
        "--agents",
        build_agents_json(),
        "--effort",
        "high",
    ]
    if model:
        cmd.extend(["--model", model])
    if continue_session:
        cmd.append("--continue")
    # Permission mode: skip interactive prompts in CI
    skip_permissions = os.environ.get("CI") == "true"
    if skip_permissions:
        cmd.append("--dangerously-skip-permissions")

    system = ctx.instructions.system
    user_prompt = prompt or ctx.instructions.user
    if system:
        cmd.extend(["--system-prompt", system])
    cmd.append(user_prompt)

    logger.info("invoking claude CLI (model={})", model or "default")
    accumulator = StreamSpanAccumulator(agent_name="claude")

    tracer = _resolve_active_tracer()

    try:
        process = spawn_agent_cli(cmd, env=_build_env(ctx))
    except FileNotFoundError:
        # W5.4 / W5.5 regression pins and the W5.7 equivalence test patch
        # only ``subprocess.run``. When the real CLI is missing AND the
        # streaming ``Popen`` path is unavailable, fall back to the
        # legacy buffered call so the failure-diagnosis contract (D13,
        # PR #16's ``_build_claude_failure_error``) and the legacy
        # ``subprocess.run`` shape both survive.
        return _run_claude_legacy_subprocess(
            cmd=cmd,
            ctx=ctx,
            model=model,
            skip_permissions=skip_permissions,
        )

    assert process.stdout is not None
    assert process.stderr is not None

    handler, close_all_open_spans = _claude_stream_event_handler(
        tracer=tracer,
        parent_span_id=None,
        model_id=model or "default",
    )

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
                return AgentResult(success=False, error="claude CLI timed out")
    finally:
        # Defensive close: the streaming event order does not guarantee
        # LIFO span closure (e.g. ``message_stop`` before ``tool_result``
        # for the same assistant turn), so any still-open spans must be
        # closed here so ``_ACTIVE_SPAN`` does not leak into the next
        # test's context. See the handler's ``close_all`` docstring.
        try:
            close_all_open_spans()
        except Exception as exc:
            logger.debug("claude stream handler cleanup failed: {}", exc)

    if returncode == 0 and stderr_text.strip():
        for line in stderr_text.strip().splitlines()[-_STDERR_TAIL_LINES:]:
            logger.debug("[claude] {}", line)

    # If the streaming read observed at least one parsed event, the
    # accumulator already holds the canonical output and usage. Surface
    # them directly. Otherwise fall back to the legacy last-line parse
    # so a non-streaming claude binary (older CLI, custom build) keeps
    # working unchanged — the recorded stream the test delivers carries
    # multiple events, so this branch is reached only on an unexpected
    # empty stream.
    if accumulator.parsed_event_count > 0:
        if returncode != 0:
            logger.warning(
                "claude CLI failed (exit={}); stderr={!r}",
                returncode,
                stderr_text,
            )
            retryable = is_retryable_cli_failure(returncode=returncode, stderr=stderr_text)
            return AgentResult(
                success=False,
                output=accumulator.final_output,
                error=_build_claude_failure_error(
                    returncode=returncode,
                    stderr=stderr_text,
                    model=model,
                    skip_permissions=skip_permissions,
                ),
                usage=accumulator.to_usage(),
                metadata={"retryable": True} if retryable else {},
            )
        return AgentResult(
            success=True,
            output=accumulator.final_output,
            usage=accumulator.to_usage(),
        )

    return AgentResult(success=False, error="claude CLI produced no events")


def _run_claude_legacy_subprocess(
    *,
    cmd: list[str],
    ctx: AgentRunContext,
    model: str | None,
    skip_permissions: bool,
) -> AgentResult:
    """Legacy ``subprocess.run`` path — preserved for the regression pins.

    W5.4 (idle detection) and W5.5 (failure diagnosis at warning) only
    monkey-patch ``subprocess.run`` on the driver module; they do not
    patch ``Popen``. When the real CLI binary is missing (i.e. the test
    environment without ``/usr/bin/claude``), the streaming Popen path
    raises ``FileNotFoundError``; this fallback keeps the legacy
    ``capture_output=True`` read loop reachable so PR #16's
    ``_build_claude_failure_error`` semantics and the failure-diagnosis
    contract continue to hold.
    """
    try:
        completed = subprocess.run(
            wrap_agent_command(cmd),
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
        return AgentResult(success=False, error="claude CLI timed out")

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if completed.returncode == 0 and stderr.strip():
        for line in stderr.strip().splitlines()[-_STDERR_TAIL_LINES:]:
            logger.debug("[claude] {}", line)

    return _run_claude_legacy_blob_parse(
        stdout=stdout,
        model=model,
        skip_permissions=skip_permissions,
        stderr=stderr,
        returncode=completed.returncode,
    )


async def _run(ctx: AgentRunContext) -> AgentResult:
    try:
        cli = await _install(None)
    except FileNotFoundError as err:
        return AgentResult(success=False, error=str(err))

    mcp_config = write_mcp_config(ctx)
    # Blocking Popen/wait/stream consume runs in a worker thread so
    # ``asyncio.wait_for`` in ``main`` can preempt the coroutine (W9.2).
    initial = await asyncio.to_thread(
        _run_claude_once,
        cli=cli,
        prompt=ctx.instructions.user,
        ctx=ctx,
        mcp_config=mcp_config,
    )

    async def resume(prompt: str) -> AgentResult:
        return await asyncio.to_thread(
            _run_claude_once,
            cli=cli,
            prompt=prompt,
            ctx=ctx,
            mcp_config=mcp_config,
            continue_session=True,
        )

    result = await run_post_run_retry_loop(ctx, initial=initial, resume=resume)
    return await finalize_agent_result(ctx, result)


claude = agent(name="claude", install=_install, run=_run, build_env=_build_env)
