"""Plan 13 W1.5 — logging and stream rendering RED contracts (W6/W7)."""

from __future__ import annotations

import io
import json
import threading
from typing import Any

import pytest

from mergecraft.agents._stream_consumer import StreamSpanAccumulator, consume_stream
from mergecraft.utils.log import configure_logging


def test_loguru_sinks_use_enqueue_true(monkeypatch: pytest.MonkeyPatch) -> None:
    from loguru import logger as loguru_logger

    added: list[dict[str, Any]] = []
    original_add = loguru_logger.add

    def _recording_add(*args: Any, **kwargs: Any) -> int:
        added.append(kwargs)
        return original_add(*args, **kwargs)

    monkeypatch.setattr(loguru_logger, "add", _recording_add)
    configure_logging(force=True)
    assert added, "expected at least one sink registration"
    assert all(entry.get("enqueue") is True for entry in added)


def test_log_queue_drain_registered_on_atexit() -> None:
    from mergecraft.utils import git_setup
    from mergecraft.utils import log as log_mod

    assert hasattr(log_mod, "drain_loguru_queue")
    assert hasattr(git_setup, "_register_log_drain")


def test_concurrent_logger_and_stream_writes_do_not_interleave(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loguru import logger

    buffer = io.StringIO()
    logger.remove()
    logger.add(buffer, format="{message}", enqueue=True)

    stop = threading.Event()

    def _logger_thread() -> None:
        for i in range(2000):
            logger.info("LOG-LINE-{:04d}-END", i)
        stop.set()

    def _stream_thread() -> None:
        acc = StreamSpanAccumulator(agent_name="codex")
        lines = (
            json.dumps({"type": "item.completed", "item": {"id": f"s{i}"}}) for i in range(2000)
        )
        consume_stream(raw_stream=lines, accumulator=acc, handler=lambda *_a, **_k: None)
        stop.set()

    t1 = threading.Thread(target=_logger_thread)
    t2 = threading.Thread(target=_stream_thread)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    output = buffer.getvalue().splitlines()
    for line in output:
        if line.startswith("LOG-LINE-"):
            assert line.endswith("-END")
        elif line.startswith("{"):
            parsed = json.loads(line)
            assert isinstance(parsed, dict)


def test_consume_stream_marks_activity_per_event(monkeypatch: pytest.MonkeyPatch) -> None:
    marks: list[str] = []
    monkeypatch.setattr(
        "mergecraft.utils.activity.mark_activity",
        lambda: marks.append("tick"),
    )

    events = [
        json.dumps({"type": "item.completed", "item": {"id": "a"}}),
        json.dumps({"type": "turn.completed"}),
    ]
    consume_stream(
        raw_stream=events,
        accumulator=StreamSpanAccumulator(agent_name="codex"),
        handler=lambda *_a, **_k: None,
    )
    assert len(marks) == 2


def test_consume_stream_does_not_echo_raw_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    writes: list[str] = []
    monkeypatch.setattr("sys.stdout.write", lambda s: writes.append(s))

    consume_stream(
        raw_stream=[json.dumps({"type": "item.completed", "item": {"id": "x"}})],
        accumulator=StreamSpanAccumulator(agent_name="codex"),
        handler=lambda *_a, **_k: None,
    )
    assert writes == []


@pytest.mark.parametrize(
    ("event", "needle"),
    [
        (
            {"type": "tool_call", "name": "checkout_pr", "arguments": {"pull_number": 1}},
            "checkout_pr",
        ),
        (
            {"type": "tool_result", "name": "get_pull_request", "duration_ms": 1200},
            "get_pull_request",
        ),
        (
            {
                "type": "tool_failure",
                "name": "checkout_pr",
                "error": "auth: could not read Username",
            },
            "checkout_pr",
        ),
    ],
)
def test_stream_render_emits_expected_line_shape(event: dict[str, Any], needle: str) -> None:
    from mergecraft.agents.stream_render import render_stream_event

    line = render_stream_event(event)
    assert needle in line
    assert line.endswith("\n") or "→" in line or "✓" in line or "✗" in line


def test_actions_step_debug_still_emits_raw_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ACTIONS_STEP_DEBUG", "true")
    configure_logging(force=True)
    raw = json.dumps({"type": "item.completed", "item": {"id": "debug"}})
    consume_stream(
        raw_stream=[raw],
        accumulator=StreamSpanAccumulator(agent_name="codex"),
        handler=lambda *_a, **_k: None,
    )
    captured = capsys.readouterr()
    assert raw in captured.out or raw in captured.err


@pytest.mark.asyncio
async def test_mcp_execute_emits_single_error_log_line() -> None:
    from loguru import logger

    from mergecraft.mcp.shared import execute

    captured: list[str] = []
    sink_id = logger.add(lambda message: captured.append(message.record["message"]), level="INFO")

    async def _boom(_params: dict[str, object]) -> None:
        msg = "simulated tool failure"
        raise RuntimeError(msg)

    try:
        handler = execute(_boom, "demo_tool")
        result = await handler({})
        assert result.is_error is True
        assert sum("simulated tool failure" in line for line in captured) == 1
    finally:
        logger.remove(sink_id)
