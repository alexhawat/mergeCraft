"""Per-attempt model usage reaches the matching ``llm.call`` span.

The step summary consumes aggregate ``ToolState.usage_entries``. These tests
protect the complementary trace contract: each executed model-chain attempt
stamps its own exact token, cache, and cost values on its ``llm.call`` span,
including retryable failures before the eventual winner.
"""

from __future__ import annotations

from typing import Any

from tests.tracing.instrumentation.conftest import make_agent_result, make_agent_usage


def _build_settings() -> Any:
    from mergecraft.config import RepoSettings

    return RepoSettings.model_validate(
        {
            "tracing": {"enabled": True, "sinks": [{"type": "memory"}]},
            "models": ["anthropic/claude-sonnet"],
        }
    )


def _drive_chain(settings: Any, results: list[Any]) -> Any:
    import asyncio

    from mergecraft.utils.agent_resolve import run_with_model_chain

    iterator = iter(results)

    async def run_once(slug: str) -> Any:
        return next(iterator)

    return asyncio.run(run_with_model_chain(settings=settings, run_once=run_once))


def test_usage_entries_are_consumed(captured_sink: Any) -> None:
    """W3.5 — token + cost attributes reach ``llm.call`` spans.

    Drives the chain with a non-trivial ``AgentUsage`` (input + output
    tokens, cache_read, cache_write, cost_usd) and asserts the captured
    ``llm.call`` span carries them.

    The accepted alternative (W4 may delete the field) is covered in
    ``test_usage_entries_field_may_be_deleted``.
    """
    from mergecraft.agents.shared import AgentResult

    settings = _build_settings()
    usage = make_agent_usage(
        input_tokens=200,
        output_tokens=80,
        cache_read_tokens=40,
        cache_write_tokens=10,
        cost_usd=0.0123,
    )
    results = [AgentResult(success=True, usage=usage)]
    _drive_chain(settings, results)

    captured_sink.record()
    llm_calls = captured_sink.by_kind.get("llm.call", [])
    assert llm_calls, "no llm.call spans recorded — usage has no consumer"

    attrs = llm_calls[0].attrs
    assert attrs["cost.tokens_in"] == 200
    assert attrs["cost.tokens_out"] == 80
    assert attrs["cost.cache_read"] == 40
    assert attrs["cost.cache_write"] == 10
    assert attrs["cost.usd"] == 0.0123


def test_each_executed_attempt_carries_its_own_usage(captured_sink: Any) -> None:
    """Retry usage stays on its attempt rather than leaking to the winner."""
    settings = _build_settings().model_copy(
        update={"models": ["anthropic/claude-sonnet", "openai/gpt-5"]}
    )
    results = [
        make_agent_result(
            success=False,
            error="rate limited",
            retryable=True,
            usage=make_agent_usage(input_tokens=10, output_tokens=5, cost_usd=0.0001),
        ),
        make_agent_result(
            success=True,
            usage=make_agent_usage(input_tokens=20, output_tokens=8, cost_usd=0.0002),
        ),
    ]
    _drive_chain(settings, results)

    captured_sink.record()
    llm_calls = captured_sink.by_kind.get("llm.call", [])
    assert len(llm_calls) == 2
    assert [call.attrs["cost.tokens_in"] for call in llm_calls] == [10, 20]
    assert [call.attrs["cost.tokens_out"] for call in llm_calls] == [5, 8]
    assert [call.attrs["cost.usd"] for call in llm_calls] == [0.0001, 0.0002]


__all__ = [
    "test_each_executed_attempt_carries_its_own_usage",
    "test_usage_entries_are_consumed",
]
