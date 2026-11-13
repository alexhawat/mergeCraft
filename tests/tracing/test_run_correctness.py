"""Regression coverage for trace payloads and retention lifecycle."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from mergecraft.agents._stream_consumer import StreamSpanAccumulator
from mergecraft.agents.codex_stream import codex_stream_event_handler
from mergecraft.tracing import JSONLFileSink, MemorySink, TraceEvent, Tracer


def test_codex_tool_span_waits_for_matching_result() -> None:
    """The real stream handler pairs results by tool id, rather than copying input."""
    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="s", run_id="r")
    handler, close_all = codex_stream_event_handler(tracer=tracer, model_id="codex-mini")
    accumulator = StreamSpanAccumulator(agent_name="codex")
    item = {"type": "tool_call", "id": "call-1", "name": "read_file", "input": "input.txt"}
    handler(accumulator, {"type": "item.started", "item": item})
    handler(accumulator, {"type": "item.completed", "item": item})
    assert not [event for event in sink.events if event.kind == "tool.call"]
    handler(
        accumulator,
        {
            "type": "item.completed",
            "item": {
                "type": "tool_result",
                "id": "result-1",
                "tool_call_id": "call-1",
                "output": "file contents",
            },
        },
    )
    close_all()
    calls = [event for event in sink.events if event.kind == "tool.call"]
    assert len(calls) == 1
    assert calls[0].attrs["tool.input"] == "input.txt"
    assert calls[0].attrs["tool.output"] == "file contents"


@pytest.mark.parametrize("failed", [False, True], ids=["result", "error"])
def test_codex_cli_mcp_tool_item_records_completed_response(failed: bool) -> None:
    """Trace the MCP item shape emitted by the pinned Codex CLI."""
    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="s", run_id="r")
    handler, close_all = codex_stream_event_handler(tracer=tracer, model_id="codex-mini")
    accumulator = StreamSpanAccumulator(agent_name="codex")
    item = {
        "type": "mcp_tool_call",
        "id": "item_1",
        "server": "mergecraft",
        "tool": "read_file",
        "arguments": {"path": "input.txt", "password": "fixture-password"},
        "result": None,
        "error": None,
        "status": "in_progress",
    }
    handler(accumulator, {"type": "item.started", "item": item})
    assert not [event for event in sink.events if event.kind == "tool.call"]
    result = {
        "content": [{"type": "text", "text": "file contents"}],
        "structured_content": {"token": "fixture-token"},
    }
    error = {"message": "file missing"}
    handler(
        accumulator,
        {
            "type": "item.completed",
            "item": {
                **item,
                "result": None if failed else result,
                "error": error if failed else None,
                "status": "failed" if failed else "completed",
            },
        },
    )
    calls = [event for event in sink.events if event.kind == "tool.call"]
    assert len(calls) == 1
    assert calls[0].attrs["tool.server"] == "mergecraft"
    attrs = calls[0].attrs
    assert attrs["tool.input"] == {"path": "input.txt", "password": "<redacted>"}
    redacted_result = {**result, "structured_content": {"token": "<redacted>"}}
    assert attrs["tool.output"] == (error if failed else redacted_result)
    assert attrs["tool.exit_code"] == ("error" if failed else "ok")
    assert "fixture-password" not in attrs["gen_ai.tool.input"]
    assert "fixture-token" not in attrs["gen_ai.tool.output"]
    close_all()
    assert len([event for event in sink.events if event.kind == "tool.call"]) == 1


def test_jsonl_retention_runs_on_open_only(
    tmp_path: Path, trace_event_data: dict[str, Any]
) -> None:
    """A new sink purges old daily files once and never touches unrelated JSONL."""
    now = datetime(2026, 11, 13, tzinfo=UTC)
    old_time = (now - timedelta(days=60)).timestamp()
    old = tmp_path / "2026-01-01.jsonl"
    unrelated = tmp_path / "audit.jsonl"
    for path in (old, unrelated):
        path.write_text("old\n")
        os.utime(path, (old_time, old_time))
    sink = JSONLFileSink(tmp_path, clock=lambda: now)
    assert not old.exists()
    assert unrelated.exists()
    old.write_text("arrived after open\n")
    os.utime(old, (old_time, old_time))
    for _ in range(3):
        sink.write(TraceEvent.model_validate(trace_event_data))
    assert old.exists()


def test_new_review_roots_reset_span_cap_and_keep_workflow_correlation(monkeypatch: Any) -> None:
    """Repeated reviews in one Actions job retain correlation without sharing span caps."""
    from mergecraft.config import RepoSettings
    from mergecraft.tracing import tracer as trace_mod

    trace_mod.reset_process_tracer_cache()
    monkeypatch.delenv("MERGECRAFT_TRACE_ID", raising=False)
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    monkeypatch.setattr(trace_mod, "MAX_SPANS_PER_RUN", 2)
    settings = RepoSettings.model_validate(
        {"tracing": {"enabled": True, "sinks": [{"type": "memory"}]}}
    )
    sink = MemorySink()
    monkeypatch.setattr(trace_mod, "claim_sink", lambda _settings: sink)
    try:
        ids = []
        for _ in range(2):
            tracer = trace_mod.get_tracer_from_settings(settings, new_run=True)
            with trace_mod.run_root_span(tracer):
                assert trace_mod.get_tracer_from_settings(settings, new_run=True) is tracer
                with tracer.start_span("tool.call"):
                    pass
                with tracer.start_span("tool.call"):
                    pass
            ids.append(tracer.trace_id)
        assert len(set(ids)) == 2
        assert len(sink.events) == 4
        assert {event.attrs["mergecraft.run_id"] for event in sink.events} == {"123456"}
        assert "MERGECRAFT_TRACE_ID" not in os.environ
    finally:
        trace_mod.reset_process_tracer_cache()


@pytest.mark.parametrize("trace_id", [None, "f" * 32], ids=["generated", "explicit"])
async def test_detached_requests_resolve_their_own_concurrent_run(
    monkeypatch: Any, trace_id: str | None
) -> None:
    """A later review's cached tracer cannot steal an earlier review's MCP spans."""
    import asyncio
    from contextvars import Context

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import tracer as trace_mod

    trace_mod.reset_process_tracer_cache()
    monkeypatch.delenv("MERGECRAFT_TRACE_ID", raising=False)
    if trace_id is not None:
        monkeypatch.setenv("MERGECRAFT_TRACE_ID", trace_id)
    settings = RepoSettings.model_validate(
        {"tracing": {"enabled": True, "sinks": [{"type": "memory"}]}}
    )
    entered = []
    ready = asyncio.Event()

    async def review() -> str:
        tracer = trace_mod.get_tracer_from_settings(settings, new_run=True)
        with trace_mod.run_root_span(tracer):
            parent = trace_mod.current_trace_parent()
            entered.append(parent)
            if len(entered) == 2:
                ready.set()
            await asyncio.wait_for(ready.wait(), timeout=1)
            assert Context().run(trace_mod.tracer_for_trace_parent, parent) is tracer
            return tracer.trace_id

    try:
        ids = await asyncio.gather(review(), review())
        assert len(set(ids)) == (1 if trace_id else 2)
        assert all(trace_mod.tracer_for_trace_parent(parent) is None for parent in entered)
    finally:
        trace_mod.reset_process_tracer_cache()


@pytest.mark.parametrize("has_results", [True, False], ids=["results", "stream-cleanup"])
def test_pending_codex_tools_do_not_change_active_parent(has_results: bool) -> None:
    """Overlapping tool calls are siblings, including non-LIFO result delivery."""
    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="s", run_id="r")
    handler, close_all = codex_stream_event_handler(tracer=tracer, model_id="codex-mini")
    acc = StreamSpanAccumulator(agent_name="codex")
    with tracer.start_span("llm.call") as parent:
        for tool_id in ("a", "b"):
            item = {"type": "tool_call", "id": tool_id, "name": "read_file", "input": "file.txt"}
            handler(acc, {"type": "item.started", "item": item})
            handler(acc, {"type": "item.completed", "item": item})
        if has_results:
            for tool_id in ("a", "b"):
                handler(
                    acc,
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "tool_result",
                            "tool_call_id": tool_id,
                            "output": "done",
                        },
                    },
                )
        close_all()
        assert tracer.current_span() is parent
        with tracer.start_span("next") as next_span:
            assert next_span.parent_span_id == parent.span_id
    calls = [event for event in sink.events if event.kind == "tool.call"]
    assert len(calls) == 2
    assert all(event.parent_span_id == parent.span_id for event in calls)
    assert all(event.ts_start_ns > 0 for event in calls)
