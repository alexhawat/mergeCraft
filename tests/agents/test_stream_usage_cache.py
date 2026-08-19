"""W14.4 / #273 — cached-input token accounting in ``StreamSpanAccumulator``.

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-19-wave-plan.md``
(Batch D / W14 RED, W18 impl). Live anchor: ``agents/_stream_consumer.py:181``.

The defect: ``to_usage()`` returns
``input_tokens=tokens_in + cache_read + cache_write``. That is correct for
Anthropic, whose ``input_tokens`` **excludes** cache reads, and wrong for
OpenAI-shaped providers, whose ``input_tokens`` / ``prompt_tokens`` already
**include** ``prompt_tokens_details.cached_tokens``. Since T2 folded the
OpenAI shape onto the same ``cache_read`` field, every Nous / MiniMax /
opencode-Responses run over-reports its prompt tokens by the cached count.

**D16** is the binding contract, and its asymmetry is the whole difficulty:

    ``to_usage().input_tokens`` = ``tokens_in`` + ``cache_write``
    (+ ``cache_read`` **only** when it came from an Anthropic-native field).
    ``cache_read_tokens`` still reports the cached count either way.
    The Anthropic-native path is unchanged.

So both providers are pinned here. A fix that stops adding ``cache_read``
everywhere passes the OpenAI arms and silently under-reports Anthropic — the
Anthropic arms are green today precisely so they cannot be traded away.

Both accumulator entry points are covered (``replace_usage`` for the
terminal ``turn.completed`` / ``result`` event, ``absorb_usage`` for Claude's
incremental ``message_start`` / ``message_delta`` events), and the consumer
half is driven through the real ``consume_stream`` + driver handlers, since
``to_usage()`` can look right at the unit boundary while
``AgentResult.usage`` stays wrong.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from mergecraft.agents._stream_consumer import (
    StreamSpanAccumulator,
    _extract_openai_cached_tokens,
    consume_stream,
)

_INPUT = 100
_CACHED = 40
_OUTPUT = 7
_CACHE_WRITE = 25

_OPENAI_CHAT_USAGE: dict[str, Any] = {
    "input_tokens": _INPUT,
    "output_tokens": _OUTPUT,
    "prompt_tokens_details": {"cached_tokens": _CACHED},
}
_OPENAI_RESPONSES_USAGE: dict[str, Any] = {
    "input_tokens": _INPUT,
    "output_tokens": _OUTPUT,
    "input_tokens_details": {"cached_tokens": _CACHED},
}
_ANTHROPIC_USAGE: dict[str, Any] = {
    "input_tokens": _INPUT,
    "output_tokens": _OUTPUT,
    "cache_read_input_tokens": _CACHED,
}

_OPENAI_SHAPES = (
    pytest.param(_OPENAI_CHAT_USAGE, id="prompt_tokens_details"),
    pytest.param(_OPENAI_RESPONSES_USAGE, id="input_tokens_details"),
)


def _accumulate(usage: dict[str, Any], *, mode: str) -> StreamSpanAccumulator:
    acc = StreamSpanAccumulator(agent_name="test")
    if mode == "replace":
        acc.replace_usage(usage)
    else:
        acc.absorb_usage(usage)
    return acc


# ---------------------------------------------------------------------------
# The bug — OpenAI cached tokens are inclusive of the input count
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("usage", _OPENAI_SHAPES)
@pytest.mark.parametrize("mode", ["replace", "absorb"])
def test_openai_cached_tokens_are_not_added_to_input_tokens(
    usage: dict[str, Any],
    mode: str,
) -> None:
    """#273 / D16 — the cached count is already inside ``input_tokens``."""
    rendered = _accumulate(usage, mode=mode).to_usage()

    assert rendered is not None
    assert rendered.input_tokens == _INPUT
    assert rendered.cache_read_tokens == _CACHED


@pytest.mark.parametrize("usage", _OPENAI_SHAPES)
def test_openai_cached_tokens_are_still_reported(usage: dict[str, Any]) -> None:
    """Green guard: the fix must stop *adding* the cached count, not *recording* it.

    Dropping ``cache_read`` to zero would make the arm above pass while
    losing the cost signal Logfire renders as ``cost.cache_read``.
    """
    rendered = _accumulate(usage, mode="replace").to_usage()

    assert rendered is not None
    assert rendered.cache_read_tokens == _CACHED
    assert rendered.output_tokens == _OUTPUT


def test_openai_cache_write_stays_additive_while_reads_do_not() -> None:
    """D16 splits the two buckets: writes add, inclusive reads do not.

    ``cache_write`` is a genuinely disjoint count on every provider that
    reports one, so the fix must be scoped to the read bucket.
    """
    usage = {**_OPENAI_CHAT_USAGE, "cacheWriteTokens": _CACHE_WRITE}
    rendered = _accumulate(usage, mode="replace").to_usage()

    assert rendered is not None
    assert rendered.input_tokens == _INPUT + _CACHE_WRITE
    assert rendered.cache_read_tokens == _CACHED
    assert rendered.cache_write_tokens == _CACHE_WRITE


# ---------------------------------------------------------------------------
# The half that must NOT move — Anthropic counters are disjoint
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["replace", "absorb"])
def test_anthropic_cache_read_stays_additive(mode: str) -> None:
    """Green guard: Anthropic's ``input_tokens`` excludes cache reads.

    Green today and it must stay green. This is the arm that fails if W18
    "fixes" #273 by removing ``+ self.cache_read`` from ``to_usage()``
    outright.
    """
    rendered = _accumulate(_ANTHROPIC_USAGE, mode=mode).to_usage()

    assert rendered is not None
    assert rendered.input_tokens == _INPUT + _CACHED
    assert rendered.cache_read_tokens == _CACHED


def test_anthropic_full_shape_sums_both_cache_buckets() -> None:
    """Green guard: Anthropic reads *and* writes are both disjoint additions."""
    usage = {**_ANTHROPIC_USAGE, "cache_creation_input_tokens": _CACHE_WRITE}
    rendered = _accumulate(usage, mode="replace").to_usage()

    assert rendered is not None
    assert rendered.input_tokens == _INPUT + _CACHED + _CACHE_WRITE
    assert rendered.cache_read_tokens == _CACHED
    assert rendered.cache_write_tokens == _CACHE_WRITE


def test_anthropic_native_field_wins_over_an_openai_details_block() -> None:
    """Green guard: the resolution order that makes the two paths separable.

    ``cache_read_input_tokens`` is consulted before
    ``_extract_openai_cached_tokens``, so a payload carrying both is
    unambiguously Anthropic-native — which is what lets W18 tell the two
    provenances apart with a single flag.
    """
    usage = {
        "input_tokens": _INPUT,
        "output_tokens": _OUTPUT,
        "cache_read_input_tokens": _CACHED,
        "prompt_tokens_details": {"cached_tokens": 999},
    }
    rendered = _accumulate(usage, mode="replace").to_usage()

    assert rendered is not None
    assert rendered.cache_read_tokens == _CACHED
    assert rendered.input_tokens == _INPUT + _CACHED


def test_no_cache_fields_leaves_input_tokens_untouched() -> None:
    """Green guard: a payload with neither cache shape is unaffected."""
    rendered = _accumulate({"input_tokens": _INPUT, "output_tokens": _OUTPUT}, mode="replace")

    usage = rendered.to_usage()
    assert usage is not None
    assert usage.input_tokens == _INPUT
    assert usage.cache_read_tokens is None
    assert usage.cache_write_tokens is None


def test_openai_extractor_still_recognises_both_shapes() -> None:
    """Green guard: T2's extractor is the provenance signal — it must not be deleted."""
    assert _extract_openai_cached_tokens(_OPENAI_CHAT_USAGE) == _CACHED
    assert _extract_openai_cached_tokens(_OPENAI_RESPONSES_USAGE) == _CACHED
    assert _extract_openai_cached_tokens(_ANTHROPIC_USAGE) == 0
    assert _extract_openai_cached_tokens({}) == 0


# ---------------------------------------------------------------------------
# Consumer half — the same numbers through the real driver handlers
# ---------------------------------------------------------------------------


def _codex_handler() -> Any:
    from mergecraft.agents.codex import _codex_stream_event_handler

    handler, _close = _codex_stream_event_handler(tracer=None, model_id="openai/gpt-5.3-codex")
    return handler


def _claude_handler() -> Any:
    from mergecraft.agents.claude import _claude_stream_event_handler

    handler, _close = _claude_stream_event_handler(
        tracer=None,
        parent_span_id=None,
        model_id="anthropic/claude-sonnet",
    )
    return handler


def _drive(events: list[dict[str, Any]], *, handler: Any, agent_name: str) -> Any:
    acc = StreamSpanAccumulator(agent_name=agent_name)
    consume_stream(
        raw_stream=[json.dumps(event) + "\n" for event in events],
        accumulator=acc,
        handler=handler,
    )
    return acc


@pytest.mark.parametrize("usage", _OPENAI_SHAPES)
def test_codex_turn_completed_reports_inclusive_cached_tokens(usage: dict[str, Any]) -> None:
    """Consumer path: ``codex exec --json`` usage reaches ``AgentResult.usage``.

    ``_run_codex_streaming`` renders ``accumulator.to_usage()`` straight onto
    the ``AgentResult``, so the unit-level arithmetic is what the reviewer's
    cost accounting sees. Driving the real handler proves the OpenAI shape
    actually reaches ``replace_usage`` rather than being filtered upstream.
    """
    acc = _drive(
        [
            {"type": "thread.started", "thread_id": "t1"},
            {"type": "turn.completed", "usage": usage},
        ],
        handler=_codex_handler(),
        agent_name="codex",
    )

    assert acc.parsed_event_count == 2
    rendered = acc.to_usage()
    assert rendered is not None
    assert rendered.input_tokens == _INPUT
    assert rendered.cache_read_tokens == _CACHED


def test_claude_result_event_keeps_anthropic_accounting() -> None:
    """Green guard on the consumer half: Claude's stream must still sum.

    ``message_start`` absorbs, then the terminal ``result`` event replaces
    with the authoritative total (the W5.7 equivalence contract). Both hops
    go through the arithmetic W18 is editing.
    """
    acc = _drive(
        [
            {"type": "message_start", "message": {"id": "m1", "usage": _ANTHROPIC_USAGE}},
            {"type": "result", "usage": _ANTHROPIC_USAGE},
        ],
        handler=_claude_handler(),
        agent_name="claude",
    )

    rendered = acc.to_usage()
    assert rendered is not None
    assert rendered.input_tokens == _INPUT + _CACHED
    assert rendered.cache_read_tokens == _CACHED


def test_empty_stream_still_reports_no_usage() -> None:
    """Green guard: no events ⇒ ``None``, not a zero-filled ``AgentUsage``."""
    acc = _drive([], handler=_codex_handler(), agent_name="codex")

    assert acc.parsed_event_count == 0
    assert acc.to_usage() is None
