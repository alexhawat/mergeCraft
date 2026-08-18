"""RH3 — NDJSON replay through ``consume_stream``."""

from __future__ import annotations

from mergecraft.agents._stream_consumer import StreamSpanAccumulator, consume_stream
from tests.support.provider_harness.ndjson import lines_from_blocks
from tests.support.provider_harness.schema import ResponseBlock


def test_consume_stream_replays_ordered_lines() -> None:
    lines = lines_from_blocks(
        [
            ResponseBlock(kind="text", text="alpha"),
            ResponseBlock(kind="text", text="beta"),
        ]
    )
    acc = StreamSpanAccumulator(agent_name="test")
    consume_stream(raw_stream=lines, accumulator=acc, handler=lambda _event: None)
    assert len(lines) == 2
