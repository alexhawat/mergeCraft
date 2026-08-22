"""Batch HD — Gemini/Codex ``llm.call`` span token attrs (#436).

Pins that terminal stream usage (Gemini ``result``, Codex ``turn.completed``)
reaches ``cost.tokens_*`` and ``gen_ai.usage.*`` on the traced ``llm.call``
span.
"""

from __future__ import annotations

from typing import Any

from mergecraft.agents import codex as codex_mod
from mergecraft.agents import gemini as gemini_mod
from mergecraft.agents._stream_consumer import StreamSpanAccumulator
from mergecraft.tracing.sinks import MemorySink
from mergecraft.tracing.tracer import Tracer

_GEMINI_USAGE = {"input_tokens": 40, "output_tokens": 9}
_CODEX_USAGE = {
    "input_tokens": 20,
    "output_tokens": 5,
    "output_tokens_details": {"reasoning_tokens": 4},
}


def _gemini_tracer() -> tuple[MemorySink, Tracer]:
    sink = MemorySink()
    return sink, Tracer(sink=sink, session_id="hd-gem-session", run_id="hd-gem-run")


def _gemini_spans(sink: MemorySink, kind: str) -> list[Any]:
    return [event for event in sink.events if getattr(event, "kind", None) == kind]


def _codex_handler() -> tuple[Any, Any, MemorySink, StreamSpanAccumulator]:
    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="hd-codex-session", run_id="hd-codex-run")
    handler, close_all = codex_mod._codex_stream_event_handler(
        tracer=tracer,
        model_id="gpt-5.3-codex",
    )
    return handler, close_all, sink, StreamSpanAccumulator(agent_name="codex")


def _codex_llm_attrs(sink: MemorySink) -> dict[str, Any]:
    llm_events = [event for event in sink.events if event.kind == "llm.call"]
    assert len(llm_events) == 1, f"expected one llm.call span, got {len(llm_events)}"
    return llm_events[0].attrs


def _assert_span_token_attrs(
    attrs: dict[str, Any],
    *,
    input_tokens: int,
    output_tokens: int,
) -> None:
    assert attrs["gen_ai.usage.input_tokens"] == input_tokens
    assert attrs["gen_ai.usage.output_tokens"] == output_tokens
    assert attrs["cost.tokens_in"] == input_tokens
    assert attrs["cost.tokens_out"] == output_tokens


# --- #436 Gemini ``result`` → ``llm.call`` span attrs -------------------------


def test_result_event_usage_reaches_the_llm_span_token_attrs() -> None:
    """Token counts on the terminal ``result`` event must land on ``llm.call``."""
    sink, tracer = _gemini_tracer()
    handler, close_all = gemini_mod._gemini_stream_event_handler(tracer=tracer, model_id="gemini-3")
    acc = StreamSpanAccumulator(agent_name="gemini")

    handler(acc, {"type": "init"})
    handler(
        acc,
        {"type": "result", "usage": _GEMINI_USAGE, "response": "done"},
    )
    close_all()

    _assert_span_token_attrs(
        _gemini_spans(sink, "llm.call")[0].attrs,
        input_tokens=40,
        output_tokens=9,
    )


def test_result_event_partial_usage_stamps_zero_for_missing_output_tokens() -> None:
    """A ``result`` with only ``input_tokens`` must not invent output counts."""
    sink, tracer = _gemini_tracer()
    handler, close_all = gemini_mod._gemini_stream_event_handler(tracer=tracer, model_id="gemini-3")
    acc = StreamSpanAccumulator(agent_name="gemini")

    handler(acc, {"type": "init"})
    handler(acc, {"type": "result", "usage": {"input_tokens": 12}, "response": "done"})
    close_all()

    attrs = _gemini_spans(sink, "llm.call")[0].attrs
    assert attrs["gen_ai.usage.input_tokens"] == 12
    assert attrs["gen_ai.usage.output_tokens"] == 0
    assert attrs["cost.tokens_in"] == 12
    assert attrs["cost.tokens_out"] == 0


# --- #436 Codex ``turn.completed`` → ``llm.call`` span attrs ------------------


def test_turn_completed_usage_reaches_the_llm_span_token_attrs() -> None:
    """Token counts on ``turn.completed`` must land on the thread's ``llm.call``."""
    handler, close_all, sink, acc = _codex_handler()

    handler(acc, {"type": "thread.started", "thread_id": "t1"})
    handler(
        acc,
        {
            "type": "turn.completed",
            "usage": _CODEX_USAGE,
            "total_cost_usd": 0.75,
        },
    )
    close_all()

    _assert_span_token_attrs(
        _codex_llm_attrs(sink),
        input_tokens=20,
        output_tokens=5,
    )


def test_turn_completed_partial_usage_stamps_zero_for_missing_output_tokens() -> None:
    """``turn.completed`` with only ``input_tokens`` must not invent output counts."""
    handler, close_all, sink, acc = _codex_handler()

    handler(acc, {"type": "thread.started", "thread_id": "t1"})
    handler(acc, {"type": "turn.completed", "usage": {"input_tokens": 7}})
    close_all()

    attrs = _codex_llm_attrs(sink)
    assert attrs["gen_ai.usage.input_tokens"] == 7
    assert attrs["gen_ai.usage.output_tokens"] == 0
    assert attrs["cost.tokens_in"] == 7
    assert attrs["cost.tokens_out"] == 0


# --- compatibility pins (agent usage + span attrs agree) ----------------------


def test_gemini_result_usage_reaches_both_agent_usage_and_span_attrs() -> None:
    """Run-level ``AgentUsage`` and ``llm.call`` span attrs must agree."""
    sink, tracer = _gemini_tracer()
    handler, close_all = gemini_mod._gemini_stream_event_handler(tracer=tracer, model_id="gemini-3")
    acc = StreamSpanAccumulator(agent_name="gemini")

    handler(acc, {"type": "init"})
    handler(
        acc,
        {"type": "result", "usage": _GEMINI_USAGE, "response": "done"},
    )
    close_all()

    usage = acc.to_usage()
    assert usage is not None
    assert usage.input_tokens == 40
    assert usage.output_tokens == 9

    _assert_span_token_attrs(
        _gemini_spans(sink, "llm.call")[0].attrs,
        input_tokens=40,
        output_tokens=9,
    )


def test_codex_turn_completed_usage_reaches_both_agent_usage_and_span_attrs() -> None:
    """Run-level ``AgentUsage`` and ``llm.call`` span attrs must agree."""
    handler, close_all, sink, acc = _codex_handler()

    handler(acc, {"type": "thread.started", "thread_id": "t1"})
    handler(
        acc,
        {
            "type": "turn.completed",
            "usage": _CODEX_USAGE,
            "total_cost_usd": 0.75,
        },
    )
    close_all()

    usage = acc.to_usage()
    assert usage is not None
    assert usage.input_tokens == 20
    assert usage.output_tokens == 5
    assert usage.cost_usd == 0.75

    attrs = _codex_llm_attrs(sink)
    _assert_span_token_attrs(attrs, input_tokens=20, output_tokens=5)
    assert attrs["mergecraft.usage.reasoning_tokens"] == 4
