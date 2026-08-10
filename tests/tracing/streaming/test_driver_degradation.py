"""W5.3 — non-streaming driver degrades to run-level spans (D12).

The W0.5 per-driver streaming table lists cursor as a non-streaming driver
(it talks to Cursor Cloud via HTTP polling, not a local CLI). D12 says: a
driver whose CLI cannot stream must still produce a valid root span and
must not fail the run. After W6, the migrated drivers (claude, codex,
gemini, opencode) emit per-``tool.call`` / per-``llm.call`` spans; cursor
stays at run-level.

This test pins the **degradation contract**: a recorded non-streaming
session (anything that does not return ``stream-json`` events) yields
exactly one root span (``mergecraft.run``) and no per-event spans, and
the driver returns a successful ``AgentResult``.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.mark.xfail(
    reason="green after W6: non-streaming driver degrades to run-level", strict=False
)
def test_non_streaming_driver_degrades_to_run_level(
    patch_driver_subprocess: Any,
    make_agent_run_context: Any,
    captured_streaming_sink: Any,
) -> None:
    """W5.3 — a driver whose CLI cannot stream still produces a valid root span.

    Models the cursor driver shape: a one-shot ``AgentResult`` carrying
    the final output, no per-event stream. W6 must keep the run-level
    span behaviour for non-streaming drivers — exactly one ``mergecraft.run``
    span, no ``tool.call`` / ``llm.call`` spans, and the ``AgentResult``
    is successful.
    """
    import asyncio

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import sink_factory
    from mergecraft.utils.agent_resolve import run_with_model_chain

    # Capture the run-level sink.
    settings = RepoSettings.model_validate(
        {
            "tracing": {"enabled": True, "sinks": [{"type": "memory"}]},
            "models": ["cursor/agent"],
        }
    )
    sink = sink_factory(settings.tracing)
    memory = sink.inner.sinks[0]

    # Mocked cursor-style run_once: a JSON blob, not a stream. The driver
    # can't stream this, so it must emit a run-level span and skip the
    # per-event pathway.
    async def run_once(_slug: str) -> Any:
        from mergecraft.agents.shared import AgentResult, AgentUsage

        return AgentResult(
            success=True,
            output="Cursor cloud review complete.",
            usage=AgentUsage(
                agent="cursor",
                input_tokens=200,
                output_tokens=100,
            ),
        )

    winning_slug, result = asyncio.run(run_with_model_chain(settings=settings, run_once=run_once))

    assert winning_slug == "cursor/agent"
    assert result.success is True
    assert result.output == "Cursor cloud review complete."

    # Refresh the captured events.
    captured_streaming_sink.memory = memory
    captured_streaming_sink.record()

    # Exactly one root span, no per-event spans.
    events = captured_streaming_sink.events
    roots = [e for e in events if e.parent_span_id is None]
    assert len(roots) == 1, (
        f"non-streaming driver must emit exactly one root span, got {len(roots)}"
    )
    assert roots[0].kind == "mergecraft.run", (
        f"root span must be 'mergecraft.run', got {roots[0].kind!r}"
    )

    # No per-event spans for a non-streaming driver.
    per_event_kinds = {"tool.call", "llm.call"}
    per_event_events = [e for e in events if e.kind in per_event_kinds]
    assert per_event_events == [], (
        f"non-streaming driver must not emit per-event spans, "
        f"got {[(e.kind, e.attrs.get('tool.name', e.attrs.get('model.id', '?'))) for e in per_event_events]}"
    )


@pytest.mark.xfail(
    reason="green after W6: tail-call agent result still produces run-level span", strict=False
)
def test_non_streaming_driver_with_failure_still_emits_run_span(
    patch_driver_subprocess: Any,
    make_agent_run_context: Any,
    captured_streaming_sink: Any,
) -> None:
    """W5.3 (failure-mode) — D12 also covers the failure path.

    Even when a non-streaming driver returns a failed ``AgentResult``,
    the run-level span must still be emitted (so the failure is
    observable in the trace) and the chain must not raise.
    """
    import asyncio

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import sink_factory
    from mergecraft.utils.agent_resolve import run_with_model_chain

    settings = RepoSettings.model_validate(
        {
            "tracing": {"enabled": True, "sinks": [{"type": "memory"}]},
            "models": ["cursor/agent"],
        }
    )
    sink = sink_factory(settings.tracing)
    memory = sink.inner.sinks[0]

    async def run_once(_slug: str) -> Any:
        from mergecraft.agents.shared import AgentResult

        return AgentResult(
            success=False,
            error="cursor cloud agent failed: api quota exhausted",
        )

    winning_slug, result = asyncio.run(run_with_model_chain(settings=settings, run_once=run_once))

    assert winning_slug == "cursor/agent"
    assert result.success is False
    assert "quota" in (result.error or "")

    captured_streaming_sink.memory = memory
    captured_streaming_sink.record()

    # The root span must still be emitted (status reflects the failure).
    events = captured_streaming_sink.events
    roots = [e for e in events if e.parent_span_id is None]
    assert len(roots) == 1
    assert roots[0].kind == "mergecraft.run"
    assert roots[0].status != "ok", (
        f"root span must reflect the failed run, got status={roots[0].status!r}"
    )


__all__ = [
    "test_non_streaming_driver_degrades_to_run_level",
    "test_non_streaming_driver_with_failure_still_emits_run_span",
]
