"""Codex NDJSON stream parsing and span bookkeeping for ``codex exec --json``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.agents.shared import AgentUsage, log_token_table
from mergecraft.agents.stream_bookkeeping import sync_open_pair_bookkeeping
from mergecraft.tracing._tool_attrs import (
    emit_verb_subevent,
    enrich_tool_request,
    enrich_tool_response,
)
from mergecraft.tracing.genai import (
    ModelParams,
    output_messages_attrs,
    request_attrs,
    thinking_attrs,
)
from mergecraft.tracing.redaction import redact_tool_payload
from mergecraft.tracing.tracer import (
    ProviderLLMPair,
    _close_provider_llm_pair,
    _open_provider_llm_pair,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from mergecraft.agents._stream_consumer import StreamSpanAccumulator
    from mergecraft.tracing.content import ContentCapture
    from mergecraft.tracing.tracer import Tracer

# O4 — the reasoning effort written into ``config.toml`` is the one request
# parameter the codex harness exposes to mergeCraft; the constant keeps the
# TOML value and the span attribute (``mergecraft.reasoning_effort``) from
# drifting apart.
CODEX_MODEL_REASONING_EFFORT = "high"


def parse_codex_payload(data: dict[str, Any]) -> tuple[str, AgentUsage | None]:
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


def _sole_open_llm_span(open_pairs: dict[str, ProviderLLMPair | None]) -> Any:
    """Return the llm span of the single open provider pair, else ``None``.

    Codex's ``message.completed`` / reasoning ``item.completed`` events do
    not carry the thread id, so payload attrs can only be stamped when
    exactly one pair is open (the typical shape — one thread per run).
    """
    live = [pair.llm for pair in open_pairs.values() if pair is not None]
    return live[0] if len(live) == 1 else None


def codex_stream_event_handler(
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
    open_tool_spans: dict[str, dict[str, Any]] = {}
    open_pairs: dict[str, ProviderLLMPair | None] = {}
    open_pair_bookkeeping: dict[str, dict[str, Any]] = {}

    def handler(
        accumulator: StreamSpanAccumulator,
        event: dict[str, Any],
    ) -> None:
        event_type = str(event.get("type") or "")

        if not event_type:
            output, usage = parse_codex_payload(event)
            if output:
                accumulator.set_output(output)
            if usage is not None:
                usage_dict = {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "total_cost_usd": usage.cost_usd,
                }
                accumulator.replace_usage(usage_dict)
                sync_open_pair_bookkeeping(open_pair_bookkeeping, usage_dict)
            return

        if event_type == "thread.started":
            thread_id = str(event.get("thread_id") or "default")
            if thread_id in open_pairs:
                return
            if tracer is not None:
                pair = _open_provider_llm_pair(
                    tracer,
                    model_id=model_id,
                    family="responses_api",
                    provider_id="openai_codex",
                )
                if pair is not None:
                    pair.llm.set_attribute("model.event", "thread.started")
                    pair.llm.set_attribute("gen_ai.system", "openai")
                    pair.llm.set_attribute("gen_ai.operation.name", "chat")
                    pair.llm.set_attribute("gen_ai.request.model", model_id)
                    pair.llm.set_attribute("gen_ai.response.model", model_id)
                    for attr_key, attr_value in request_attrs(
                        model=None,
                        params=ModelParams(reasoning_effort=CODEX_MODEL_REASONING_EFFORT),
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
                    enrich_tool_request(span_obj, arguments=tool_input)
                    enrich_tool_response(span_obj, output=tool_input)
                    span_obj.close()
                    emit_verb_subevent(
                        tracer,
                        parent_span_id=span_obj.span_id,
                        tool_name=resolved_name,
                        attrs=dict(span_obj._attrs),
                    )
                return
            if item_type == "tool_result":
                return
            if item_type == "reasoning":
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
                completed_thread_id = event.get("thread_id")
                active_key = (
                    completed_thread_id
                    if isinstance(completed_thread_id, str) and completed_thread_id
                    else None
                )
                sync_open_pair_bookkeeping(
                    open_pair_bookkeeping,
                    usage,
                    active_key=active_key,
                )
            cost = event.get("total_cost_usd")
            if isinstance(cost, (int, float)) and usage is not None:
                accumulator.cost_usd = float(cost)
            reasoning_tokens: int | None = None
            if isinstance(usage, dict):
                details = usage.get("output_tokens_details")
                if isinstance(details, dict) and isinstance(
                    details.get("reasoning_tokens"), (int, float)
                ):
                    reasoning_tokens = int(details["reasoning_tokens"])
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
        for key in list(reversed(list(open_pairs.keys()))):
            _close_provider_llm_pair(open_pairs.pop(key))
        open_pair_bookkeeping.clear()

    return handler, close_all
