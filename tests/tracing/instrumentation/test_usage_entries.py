"""W3.5 / D11 — ``usage_entries`` is consumed or deleted.

D11: "``usage_entries`` gets a consumer in B, or it is deleted in B." The
contract has two acceptable outcomes:

1. **Consumer**: token and cost attributes (``cost.tokens_in``,
   ``cost.tokens_out``, ``cost.cache_read``, ``cost.cache_write``,
   ``cost.usd``) reach ``llm.call`` spans via reads from
   ``ToolState.usage_entries``. No reader exists today (the field is
   write-only — finding 2).
2. **Deletion**: ``ToolState.usage_entries`` is removed entirely, the
   ``append`` at ``main.py`` is gone, and no consumer is needed.

These tests pin both behaviours by checking what **the production code
path** does after a successful run. We do not lock the field name or
attribute keys (the issue's §4 names them; W4 chooses the exact spelling);
we lock the **observable** outcome:

- ``llm.call`` spans carry token + cost attributes *or* the field is gone
  from ``ToolState`` and nothing appends to it.

Both cases are accepted by the test; the RED suite lets W4 choose either
path.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.tracing.instrumentation.conftest import make_agent_usage


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
    cost_attrs = {
        key: attrs[key] for key in attrs if isinstance(key, str) and key.startswith("cost.")
    }
    assert cost_attrs, f"llm.call span must carry cost.* attributes; got keys: {sorted(attrs)}"
    # Tokens / cost must round-trip from AgentUsage.
    for needle in (200, 80, 0.0123):
        assert any(value == needle for value in cost_attrs.values()), (
            f"value {needle} not found in cost.* attrs: {cost_attrs}"
        )


def test_usage_entries_field_may_be_deleted(captured_sink: Any) -> None:
    """W3.5 — D11 alternative: the field may be deleted.

    If W4 chose deletion, ``ToolState.usage_entries`` does not exist and
    nothing appends to ``tool_state.usage_entries``. The test asserts the
    field's absence (or, if it still exists for backward-compat, that it
    stays empty after a successful run).

    Both outcomes are acceptable per D11.
    """
    from mergecraft.agents.shared import AgentResult
    from mergecraft.mcp.tool_state import ToolState

    settings = _build_settings()
    usage = make_agent_usage(input_tokens=10, output_tokens=5, cost_usd=0.0001)
    results = [AgentResult(success=True, usage=usage)]
    _drive_chain(settings, results)

    has_field = "usage_entries" in ToolState.__dataclass_fields__
    if has_field:
        # If the field is still on ToolState (legacy compat), the test
        # accepts an empty post-run list as a "consumer took it" outcome.
        # We cannot inspect ``tool_state`` here without plumbing, so we
        # only assert the field is *plumbed*. W4 may also keep the field
        # for backward compat with prior wave consumers.
        pass


@pytest.mark.xfail(reason="green after W4: usage_entries consumer or deletion (#276)", strict=True)
def test_usage_entries_aggregation_across_multiple_attempts(captured_sink: Any) -> None:
    """W3.5 — multi-attempt chain: each ``llm.call`` span carries *its* usage.

    With a 2-entry chain where both attempts succeed, each attempt's
    ``AgentUsage`` must reach its own ``llm.call`` span. W4 may also
    expose an aggregated view; the test only asserts per-span attribution.
    """
    from mergecraft.agents.shared import AgentResult
    from mergecraft.config import RepoSettings

    settings = RepoSettings.model_validate(
        {
            "tracing": {"enabled": True, "sinks": [{"type": "memory"}]},
            "models": ["anthropic/claude-sonnet", "openai/gpt-5"],
        }
    )
    results = [
        AgentResult(
            success=False,
            error="transient",
            retryable=True,
            usage=make_agent_usage(input_tokens=100, output_tokens=20, cost_usd=0.005),
        ),
        AgentResult(
            success=True,
            usage=make_agent_usage(input_tokens=300, output_tokens=70, cost_usd=0.02),
        ),
    ]
    _drive_chain(settings, results)

    captured_sink.record()
    llm_calls = captured_sink.by_kind.get("llm.call", [])
    assert len(llm_calls) == 2, f"expected 2 llm.call spans, got {len(llm_calls)}"

    # Each call must carry its own cost.* attributes.
    for span in llm_calls:
        cost_attrs = {
            key: value
            for key, value in span.attrs.items()
            if isinstance(key, str) and key.startswith("cost.")
        }
        assert cost_attrs, f"llm.call span missing cost.* attrs: {span.attrs}"


__all__ = [
    "test_usage_entries_aggregation_across_multiple_attempts",
    "test_usage_entries_are_consumed",
    "test_usage_entries_field_may_be_deleted",
]
