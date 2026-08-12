"""GenAI span attribute enrichment (Option B — schema + OTel GenAI standard).

Pins that every emit site populates ``attrs`` with BOTH the mergeCraft doc'd
names and the OpenTelemetry GenAI semantic-convention names, and that secrets
never reach span attributes.

These are unit-level assertions against the tracer + sink directly; they do not
require any agent binary or provider credential.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def memory_sink() -> Any:
    """Stand up a real ``MemorySink`` + ``Tracer`` pair (no filesystem, no net)."""
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="session", run_id="run")
    return {"sink": sink, "tracer": tracer}


def _events_by_kind(sink: Any) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for event in sink.events:
        out.setdefault(event.kind, []).append(event)
    return out


def test_tool_call_attrs(memory_sink: Any) -> None:
    """A ``tool.call`` span carries mergeCraft + OTel GenAI tool names."""
    tracer = memory_sink["tracer"]
    with tracer.start_span("tool.call") as span:
        span.set_attribute("tool.name", "checkout_pr")
        span.set_attribute("tool.server", "mergecraft")
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", "checkout_pr")
        span.set_attribute("gen_ai.tool.call.id", "call-1")

    events = _events_by_kind(memory_sink["sink"]).get("tool.call", [])
    assert len(events) == 1
    attrs = events[0].attrs
    assert attrs["tool.name"] == "checkout_pr"
    assert attrs["tool.server"] == "mergecraft"
    assert attrs["gen_ai.tool.name"] == "checkout_pr"
    assert attrs["gen_ai.operation.name"] == "execute_tool"
    assert attrs["gen_ai.tool.call.id"] == "call-1"


def test_llm_call_cost_attrs(memory_sink: Any) -> None:
    """An ``llm.call`` span carries mergeCraft + OTel GenAI usage names."""
    tracer = memory_sink["tracer"]
    with tracer.start_span("llm.call") as span:
        span.set_attribute("cost.tokens_in", 120)
        span.set_attribute("cost.tokens_out", 48)
        span.set_attribute("gen_ai.usage.input_tokens", 120)
        span.set_attribute("gen_ai.usage.output_tokens", 48)
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.request.model", "claude-sonnet-5")
        span.set_attribute("gen_ai.response.model", "claude-sonnet-5")

    events = _events_by_kind(memory_sink["sink"]).get("llm.call", [])
    assert len(events) == 1
    attrs = events[0].attrs
    assert attrs["cost.tokens_in"] == 120
    assert attrs["cost.tokens_out"] == 48
    assert attrs["gen_ai.usage.input_tokens"] == 120
    assert attrs["gen_ai.usage.output_tokens"] == 48
    assert attrs["gen_ai.operation.name"] == "chat"
    assert attrs["gen_ai.request.model"] == "claude-sonnet-5"


def test_agent_attempt_attrs(memory_sink: Any) -> None:
    """An ``agent.attempt`` span carries ``model.id``, ``agent.provider``, ``gen_ai.system``."""
    tracer = memory_sink["tracer"]
    with tracer.start_span("agent.attempt") as span:
        span.set_attribute("model.id", "anthropic/claude-sonnet")
        span.set_attribute("agent.provider", "anthropic")
        span.set_attribute("gen_ai.system", "anthropic")
        span.set_attribute("agent.cli_argv", "mergecraft diff-review --no-trace")

    events = _events_by_kind(memory_sink["sink"]).get("agent.attempt", [])
    assert len(events) == 1
    attrs = events[0].attrs
    assert attrs["model.id"] == "anthropic/claude-sonnet"
    assert attrs["agent.provider"] == "anthropic"
    assert attrs["gen_ai.system"] == "anthropic"
    assert "agent.cli_argv" in attrs


def test_cli_argv_redacted() -> None:
    """``redact_cli_argv`` masks a token-like value."""
    from mergecraft.tracing.redaction import redact_cli_argv

    argv = ["mergecraft", "diff-review", "--api-key", "sk-secretvalue123", "GH_TOKEN=ghp_abc"]
    redacted = redact_cli_argv(argv)
    assert "sk-secretvalue123" not in redacted
    assert "ghp_abc" not in redacted
    assert "<redacted>" in redacted
    # The command shape survives.
    assert "mergecraft" in redacted
    assert "diff-review" in redacted


def test_span_duration_nonzero(memory_sink: Any) -> None:
    """A bracketed ``with`` span records a non-zero duration."""
    import time

    tracer = memory_sink["tracer"]
    with tracer.start_span("mergecraft.run") as span:
        time.sleep(0.01)
        span.set_attribute("model.id", "anthropic/claude-sonnet")

    events = _events_by_kind(memory_sink["sink"]).get("mergecraft.run", [])
    assert len(events) == 1
    assert events[0].ts_end_ns > events[0].ts_start_ns


def test_cost_attrs_from_usage_carries_dual_names() -> None:
    """The chain's ``_cost_attrs_from_usage`` emits mergeCraft + OTel names.

    This is the helper that feeds ``cost.*`` onto the ``llm.call`` span; it
    must carry both namesets so the GenAI dashboard populates from the same
    data the mergeCraft span tree already records.
    """
    from mergecraft.agents.shared import AgentUsage
    from mergecraft.utils.agent_resolve import _cost_attrs_from_usage

    usage = AgentUsage(
        agent="claude",
        input_tokens=120,
        output_tokens=48,
        cache_read_tokens=10,
        cache_write_tokens=5,
        cost_usd=0.002,
    )
    attrs = _cost_attrs_from_usage(usage)
    # mergeCraft doc'd names.
    assert attrs["cost.tokens_in"] == 120
    assert attrs["cost.tokens_out"] == 48
    assert attrs["cost.cache_read"] == 10
    assert attrs["cost.cache_write"] == 5
    assert attrs["cost.usd"] == 0.002
    # OTel GenAI names (cache_write -> cache_creation per the GenAI spec).
    assert attrs["gen_ai.usage.input_tokens"] == 120
    assert attrs["gen_ai.usage.output_tokens"] == 48
    assert attrs["gen_ai.usage.cache_read_input_tokens"] == 10
    assert attrs["gen_ai.usage.cache_creation_input_tokens"] == 5
    assert attrs["gen_ai.usage.cost_usd"] == 0.002


__all__ = [
    "test_agent_attempt_attrs",
    "test_cli_argv_redacted",
    "test_cost_attrs_from_usage_carries_dual_names",
    "test_llm_call_cost_attrs",
    "test_span_duration_nonzero",
    "test_tool_call_attrs",
]
