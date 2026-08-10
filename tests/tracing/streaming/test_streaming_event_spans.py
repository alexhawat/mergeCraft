"""W5.1, W5.2, W5.6, W5.7 — per-event spans from a recorded stream.

The W6 implementation will switch ``agents/claude.py`` and ``agents/codex.py``
to ``--output-format stream-json`` (or ``codex exec --json``) and consume the
event stream incrementally. The four contracts here pin the shape of the
spans and the robustness of the parser.

All four tests are ``@pytest.mark.xfail(strict=False)`` — they are expected
to fail until W6 wires the streaming read loop. After W6 lands, the test-
creator will be re-dispatched to remove the markers and the tests will pass
without modification.

Design notes
------------

- The recorded stream is delivered via ``patch_driver_subprocess`` (current
  driver shape is ``subprocess.run``; W6 will likely switch to
  ``subprocess.Popen`` — the patch handles both).
- The driver is invoked with the truncated ``--output-format`` family: this
  fixture deliberately writes the **full stream** to ``stdout`` so that
  the parser must iterate even if the driver still uses ``capture_output=True``.
  W6 must therefore switch to a streaming read or to per-line iteration to
  pass the test.
- The ``captured_streaming_sink`` fixture routes tracing through the
  production ``sink_factory`` and the MemorySink. The driver must use the
  standard tracer pathway (``get_tracer_from_settings`` or W6's chosen
  injection mechanism) so the spans land here.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from tests.tracing.streaming.conftest import (
    CLAUDE_TOOL_CALL_STREAM,
    CODEX_TOOL_CALL_STREAM,
    MALFORMED_STREAM,
    serialize_stream,
)

if TYPE_CHECKING:
    pass  # noqa: TC005


# ----------------------------------------------------------------------------
# W5.1 — per-tool.call spans
# ----------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after W6: tool.call spans from stream-json", strict=False)
def test_streaming_events_produce_tool_call_spans(
    patch_driver_subprocess: Any,
    make_agent_run_context: Any,
    captured_streaming_sink: Any,
) -> None:
    """W5.1 — one ``tool.call`` span per tool event with timing.

    Drives ``_run_claude_once`` with a recorded stream fixture that includes
    exactly one ``tool_use`` + ``tool_result`` pair. After W6 migrates the
    driver to ``stream-json`` consumption, the read loop must emit one
    ``tool.call`` span whose ``attrs`` carry the tool name and identifiers,
    and whose ``ts_end_ns`` is greater than ``ts_start_ns`` (i.e. the parser
    measures tool-call duration).
    """
    from mergecraft.agents.claude import _run_claude_once

    recorded_stdout = serialize_stream(CLAUDE_TOOL_CALL_STREAM)
    recorded = patch_driver_subprocess(
        "mergecraft.agents.claude",
        stdout=recorded_stdout,
        stderr="",
        returncode=0,
    )

    ctx = make_agent_run_context()
    result = _run_claude_once(
        cli="/usr/bin/claude",
        prompt="review this diff",
        ctx=ctx,
        mcp_config=str(ctx.tmpdir) + "/mcp.json",
    )

    assert result.success, f"driver failed: {result.error!r}"
    assert recorded["cmd"], "driver did not invoke subprocess"

    captured_streaming_sink.record()
    tool_spans = captured_streaming_sink.by_kind.get("tool.call", [])
    assert len(tool_spans) == 1, (
        f"expected exactly 1 tool.call span, got {len(tool_spans)}: "
        f"{[s.attrs.get('tool.name') for s in tool_spans]}"
    )

    span = tool_spans[0]
    assert span.attrs.get("tool.name") == "Read", (
        f"first tool.call should be the Read event, got {span.attrs.get('tool.name')!r}"
    )
    # The span must carry timing — ts_end_ns must be >= ts_start_ns (a driver
    # that emits without measuring has a zero-duration span and is broken).
    assert span.ts_end_ns >= span.ts_start_ns, (
        f"tool.call span has invalid timing: start={span.ts_start_ns} end={span.ts_end_ns}"
    )
    # And the duration must be a real interval (W6 must apply monotonic
    # `time.time_ns`; an instantaneous emission is also broken).
    assert span.ts_end_ns > span.ts_start_ns, (
        "tool.call span has zero duration; W6 must measure tool-call timing"
    )


# ----------------------------------------------------------------------------
# W5.2 — per-llm.call spans with token attributes
# ----------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after W6: llm.call spans with token attrs", strict=False)
def test_streaming_events_produce_llm_call_spans(
    patch_driver_subprocess: Any,
    make_agent_run_context: Any,
    captured_streaming_sink: Any,
) -> None:
    """W5.2 — one ``llm.call`` span per message with token attributes.

    The recorded Claude stream has two ``message_start`` events (one per
    turn). After W6, each turn must produce one ``llm.call`` span with
    ``cost.tokens_in`` / ``cost.tokens_out`` populated from the event's
    ``usage`` field, and ``model.id`` carried forward to the span attrs.
    """
    from mergecraft.agents.claude import _run_claude_once

    recorded_stdout = serialize_stream(CLAUDE_TOOL_CALL_STREAM)
    patch_driver_subprocess(
        "mergecraft.agents.claude",
        stdout=recorded_stdout,
        stderr="",
        returncode=0,
    )

    ctx = make_agent_run_context(resolved_model="anthropic/claude-sonnet-5")
    result = _run_claude_once(
        cli="/usr/bin/claude",
        prompt="review this diff",
        ctx=ctx,
        mcp_config=str(ctx.tmpdir) + "/mcp.json",
    )
    assert result.success, f"driver failed: {result.error!r}"

    captured_streaming_sink.record()
    llm_spans = captured_streaming_sink.by_kind.get("llm.call", [])
    assert len(llm_spans) == 2, (
        f"expected 2 llm.call spans (one per message turn), got {len(llm_spans)}"
    )

    # Turn 1: input_tokens=100, output_tokens=0 (the message_start event).
    first = llm_spans[0]
    assert first.attrs.get("cost.tokens_in") == 100, (
        f"first span tokens_in should be 100, got {first.attrs.get('cost.tokens_in')!r}"
    )
    # Turn 2: input_tokens=50, output_tokens=0 from the message_start, with
    # the message_delta adding output_tokens=20 at the end. The aggregated
    # number must be >= 20 (W6 owns the aggregation policy).
    second = llm_spans[1]
    assert second.attrs.get("cost.tokens_in") == 50, (
        f"second span tokens_in should be 50, got {second.attrs.get('cost.tokens_in')!r}"
    )
    assert second.attrs.get("cost.tokens_out", 0) >= 20, (
        f"second span tokens_out should be >= 20, got {second.attrs.get('cost.tokens_out')!r}"
    )

    # Every llm.call span must carry the model identifier.
    for span in llm_spans:
        assert span.attrs.get("model.id"), f"llm.call span missing model.id: {span.attrs!r}"


# ----------------------------------------------------------------------------
# W5.6 — malformed stream event is skipped, not fatal
# ----------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after W6: malformed line is skipped, not fatal", strict=False)
def test_malformed_stream_event_is_skipped_not_fatal(
    patch_driver_subprocess: Any,
    make_agent_run_context: Any,
    captured_streaming_sink: Any,
) -> None:
    """W5.6 — a truncated or unparseable line does not fail the review.

    The W6 read loop must skip any line whose ``json.loads`` raises and
    continue to the next event. The driver must still return a successful
    ``AgentResult`` whose ``output`` is the ``result`` event's text.
    """
    from mergecraft.agents.claude import _run_claude_once

    recorded_stdout = serialize_stream(MALFORMED_STREAM)
    patch_driver_subprocess(
        "mergecraft.agents.claude",
        stdout=recorded_stdout,
        stderr="",
        returncode=0,
    )

    ctx = make_agent_run_context()
    result = _run_claude_once(
        cli="/usr/bin/claude",
        prompt="review this diff",
        ctx=ctx,
        mcp_config=str(ctx.tmpdir) + "/mcp.json",
    )

    # The driver must not raise; the review must succeed despite the
    # truncated line in the middle of the stream.
    assert result.success is True, (
        f"driver failed on malformed stream: error={result.error!r} output={result.output!r}"
    )
    assert result.output is not None, f"driver returned no output: {result.error!r}"
    assert "ok" in result.output, (
        f"expected the 'result' event's text to be surfaced as output, got {result.output!r}"
    )

    # The parser must have processed both well-formed sides of the
    # truncated line. At minimum the result event's usage must reach the
    # AgentResult (cost / token accounting).
    if result.usage is not None:
        assert result.usage.input_tokens >= 10, (
            f"input_tokens should reflect the message_start event's usage, "
            f"got {result.usage.input_tokens!r}"
        )


# ----------------------------------------------------------------------------
# W5.7 — streaming result parses to the same AgentResult as before
# ----------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after W6: streaming result matches blob result", strict=False)
def test_streaming_result_parsing_matches_previous_final_result(
    patch_driver_subprocess: Any,
    make_agent_run_context: Any,
) -> None:
    """W5.7 — ``AgentResult`` is equivalent before and after the migration.

    Captures the canonical ``AgentResult`` from the **current** blob-parsing
    path (last-line JSON) and the **W6** streaming path against the same
    recorded session, and asserts they match on the contract surface:

    - ``success`` is True.
    - ``output`` carries the ``result`` event's text.
    - ``usage.input_tokens`` / ``output_tokens`` / ``cost_usd`` are equal.

    Tests the "did we break the actual review" property: a streaming parser
    that drops the final ``result`` event (or fumbles the cost accounting)
    is functionally equivalent to a broken review.
    """
    from mergecraft.agents.claude import _run_claude_once

    # Drive the streaming-shaped path.
    recorded_stdout = serialize_stream(CLAUDE_TOOL_CALL_STREAM)
    patch_driver_subprocess(
        "mergecraft.agents.claude",
        stdout=recorded_stdout,
        stderr="",
        returncode=0,
    )

    ctx = make_agent_run_context()
    streaming_result = _run_claude_once(
        cli="/usr/bin/claude",
        prompt="review this diff",
        ctx=ctx,
        mcp_config=str(ctx.tmpdir) + "/mcp.json",
    )

    # Drive the legacy blob-parsing path against the same data: the current
    # claude driver reads the **last** JSON line and decodes it as the
    # result payload. The recorded stream's last line is the ``result``
    # event, so the legacy path must surface the same fields.
    legacy_blob = json.dumps(CLAUDE_TOOL_CALL_STREAM[-1])

    def _patch_driver_subprocess_for_blob(
        legacy_blob: str,
        patch_driver_subprocess: Any,
    ) -> Any:
        return patch_driver_subprocess(
            "mergecraft.agents.claude",
            stdout=legacy_blob,
            stderr="",
            returncode=0,
        )

    _patch_driver_subprocess_for_blob(legacy_blob, patch_driver_subprocess)
    legacy_result = _run_claude_once(
        cli="/usr/bin/claude",
        prompt="review this diff",
        ctx=ctx,
        mcp_config=str(ctx.tmpdir) + "/mcp.json",
    )

    # Both paths must succeed.
    assert streaming_result.success is True
    assert legacy_result.success is True

    # Output must match on the contract surface.
    assert streaming_result.output is not None
    assert legacy_result.output is not None
    assert streaming_result.output == legacy_result.output, (
        f"output mismatch: streaming={streaming_result.output!r} legacy={legacy_result.output!r}"
    )

    # Token / cost accounting must match.
    assert streaming_result.usage is not None
    assert legacy_result.usage is not None
    assert streaming_result.usage.input_tokens == legacy_result.usage.input_tokens, (
        f"input_tokens mismatch: streaming={streaming_result.usage.input_tokens} "
        f"legacy={legacy_result.usage.input_tokens}"
    )
    assert streaming_result.usage.output_tokens == legacy_result.usage.output_tokens, (
        f"output_tokens mismatch: streaming={streaming_result.usage.output_tokens} "
        f"legacy={legacy_result.usage.output_tokens}"
    )
    assert streaming_result.usage.cost_usd == legacy_result.usage.cost_usd, (
        f"cost_usd mismatch: streaming={streaming_result.usage.cost_usd} "
        f"legacy={legacy_result.usage.cost_usd}"
    )


# ----------------------------------------------------------------------------
# Smoke — the recorded-stream fixtures themselves round-trip
# ----------------------------------------------------------------------------
#
# This is not a W5 deliverable but a sanity test that the fixtures stay
# valid JSONL. If a future change to the fixture breaks the JSONL shape,
# parsing fails before the assertions even run and the xfail outcome is
# misleading. Pinning the parsing here keeps the diagnostic surface clean.

parse_final_result_check = pytest.mark.parametrize(
    ("stream", "expected_result"),
    [
        (CLAUDE_TOOL_CALL_STREAM, "Review complete: 1 issue found"),
        (CODEX_TOOL_CALL_STREAM, None),  # codex shape carries no top-level result text
    ],
)


@parse_final_result_check
def test_recorded_stream_fixtures_round_trip_through_jsonl(
    stream: list[dict[str, Any]],
    expected_result: str | None,
) -> None:
    """Sanity — the recorded-stream fixtures serialize to parseable JSONL.

    Pins the fixture shape so that ``json.loads(line)`` on every line
    succeeds. The Claude fixture ends with a ``result`` event whose
    ``result`` field is the agent's text; the codex fixture ends with a
    ``turn.completed`` and no top-level result text.
    """
    lines = list(stream_lines(stream))
    assert lines, "fixture is empty"
    for line in lines:
        parsed = json.loads(line)  # raises on malformed
        assert isinstance(parsed, dict), f"line not a JSON object: {line!r}"

    # The Claude fixture's last line is the result event with the expected
    # text; the codex fixture's last line is a turn.completed event.
    if expected_result is not None:
        final_event = json.loads(lines[-1])
        assert final_event.get("type") == "result"
        assert final_event.get("result") == expected_result


def stream_lines(stream: list[dict[str, Any] | str]) -> Any:
    """Local indirection so the parametrize table reads cleanly."""
    from tests.tracing.streaming.conftest import stream_lines as _impl

    return list(_impl(stream))


__all__ = [
    "test_malformed_stream_event_is_skipped_not_fatal",
    "test_recorded_stream_fixtures_round_trip_through_jsonl",
    "test_streaming_events_produce_llm_call_spans",
    "test_streaming_events_produce_tool_call_spans",
    "test_streaming_result_parsing_matches_previous_final_result",
]
