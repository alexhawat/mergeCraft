"""W3.8 / convention 6 — emit failure never fails the run.

The Batch A convention-6 test (``test_sink_failure_never_fails_the_run``)
pins that a sink raising on ``write`` is swallowed and logged. W3.8
re-asserts the contract at the **emit-site** layer: if the sink that the
production emit sites route through raises (or times out, or is
unreachable), the review run continues with identical semantics.

Three observable outcomes pinned:

1. **No exception propagates**: ``run_with_model_chain`` returns its
   normal tuple even when the configured sink raises on every write.
2. **The AgentResult is unchanged**: the agent's ``success`` and
   ``output`` reach the caller regardless of sink failures.
3. **A warning is logged**: at least one ``logger.warning`` is recorded
   with the failure signature.

The test wires a deliberately-raising sink into ``sink_factory`` and
exercises the production emit path through ``run_with_model_chain``.
"""

from __future__ import annotations

from typing import Any

from tests.tracing.instrumentation.conftest import (
    make_agent_result,
    make_agent_usage,
)

from mergecraft.utils.log import logger


class _RaisingSink:
    """Sink that raises ``OSError`` on every write — pin for convention 6."""

    def __init__(self) -> None:
        self.write_calls = 0

    def write(self, event: Any) -> None:
        self.write_calls += 1
        msg = "trace sink unreachable"
        raise OSError(msg)


def _drive_chain_with_raising_sink(results: list[Any]) -> tuple[Any, Any]:
    """Drive ``run_with_model_chain`` with a raising sink wired through ``sink_factory``."""

    import asyncio

    from mergecraft.config import RepoSettings
    from mergecraft.utils.agent_resolve import run_with_model_chain

    settings = RepoSettings.model_validate(
        {
            "tracing": {"enabled": True, "sinks": [{"type": "memory"}]},
            "models": ["anthropic/claude-sonnet"],
        }
    )

    raising_sink = _RaisingSink()

    # W4 must route through ``sink_factory(settings.tracing)``. We swap
    # the resulting sink for the raising sink by monkey-patching the
    # ``MultiSink`` constructor — until W4 lands, the swap is a no-op
    # and the test will be xfail.
    from mergecraft.tracing import sink_factory
    from mergecraft.tracing.sinks import MultiSink

    real_multi = MultiSink

    def patched_multi(sinks: list[Any]) -> Any:
        # Force every sink in the fan-out to be the raising one.
        return real_multi([raising_sink])

    sink_factory.__globals__["MultiSink"] = patched_multi  # type: ignore[attr-defined]

    iterator = iter(results)

    async def run_once(slug: str) -> Any:
        return next(iterator)

    try:
        outcome = asyncio.run(run_with_model_chain(settings=settings, run_once=run_once))
    finally:
        sink_factory.__globals__["MultiSink"] = real_multi  # type: ignore[attr-defined]
    return outcome, raising_sink


def test_emit_failure_never_fails_the_run() -> None:
    """W3.8 — a sink that raises on every write is swallowed.

    Drives the chain through ``run_with_model_chain`` with a deliberately
    raising sink. Asserts:

    - no exception propagates out of ``run_with_model_chain``;
    - the returned ``AgentResult`` reflects the agent's outcome (success);
    - the raising sink was actually invoked (so we know we tested the
      emit path).
    """
    results = [make_agent_result(success=True, usage=make_agent_usage())]
    (winning_slug, result), raising_sink = _drive_chain_with_raising_sink(results)

    assert winning_slug == "anthropic/claude-sonnet"
    assert result.success is True
    assert result.error is None
    assert raising_sink.write_calls >= 1, "raising sink was never invoked — emit path not exercised"


def test_emit_failure_logs_a_warning() -> None:
    """W3.8 (error logging) — sink failures are logged at ``logger.warning``.

    A dedicated ``logger.add`` sink is used because loguru binds ``sys.stderr``
    at configure time; ``capsys`` misses warnings after an earlier test has
    already configured logging.
    """
    results = [make_agent_result(success=True, usage=make_agent_usage())]
    messages: list[str] = []
    sink_id = logger.add(
        lambda record: messages.append(record.record["message"]),
        level="WARNING",
    )
    try:
        _drive_chain_with_raising_sink(results)
    finally:
        logger.remove(sink_id)
    assert any("trace sink" in message for message in messages), (
        f"expected a warning naming the trace sink; got: {messages!r}"
    )


__all__ = [
    "test_emit_failure_logs_a_warning",
    "test_emit_failure_never_fails_the_run",
]
