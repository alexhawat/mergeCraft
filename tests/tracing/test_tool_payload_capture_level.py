"""Tool span payload bodies follow the run's content-capture level.

The claude, codex and gemini stream handlers each stamp tool arguments and
results on ``tool.call`` spans. On a run whose review context reports a
non-trusted tier the ``metadata`` cap applies to those bodies too: each body is
replaced by ``.bytes`` / ``.sha256`` of the original, unless an operator-owned
source opts in to exporting bodies. Trusted runs keep the bodies.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.tracing.tool_payload import TOOL_PAYLOAD_ATTRS

if TYPE_CHECKING:
    from collections.abc import Callable

_INPUT_MARKER = "input-marker-7f3a"
_OUTPUT_MARKER = "output-marker-9c1d"


@pytest.fixture(autouse=True)
def _clean_capture_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    for key in ("MERGECRAFT_TRACING_CONTENT", "MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT"):
        monkeypatch.delenv(key, raising=False)
    # ``resolve_capture_policy`` reads ``.mergecraft/config.yaml`` from the cwd.
    monkeypatch.chdir(tmp_path)


def _claude(tracer: Any) -> None:
    from mergecraft.agents._stream_consumer import StreamSpanAccumulator
    from mergecraft.agents.claude import _claude_stream_event_handler

    handler, close_all = _claude_stream_event_handler(
        tracer=tracer, parent_span_id=None, model_id="claude-sonnet-4"
    )
    acc = StreamSpanAccumulator(agent_name="claude")
    handler(
        acc,
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "tool-1",
                "name": "Read",
                "input": {"file_path": _INPUT_MARKER},
            },
        },
    )
    handler(acc, {"type": "tool_result", "tool_use_id": "tool-1", "content": _OUTPUT_MARKER})
    close_all()


def _codex(tracer: Any) -> None:
    from mergecraft.agents._stream_consumer import StreamSpanAccumulator
    from mergecraft.agents.codex_stream import codex_stream_event_handler

    handler, close_all = codex_stream_event_handler(tracer=tracer, model_id="codex-mini")
    acc = StreamSpanAccumulator(agent_name="codex")
    item = {"type": "tool_call", "id": "tool-1", "name": "shell", "input": _INPUT_MARKER}
    handler(acc, {"type": "item.started", "item": item})
    handler(acc, {"type": "item.completed", "item": item})
    handler(
        acc,
        {
            "type": "item.completed",
            "item": {
                "type": "tool_result",
                "tool_call_id": "tool-1",
                "output": _OUTPUT_MARKER,
            },
        },
    )
    close_all()


def _gemini(tracer: Any) -> None:
    from mergecraft.agents._stream_consumer import StreamSpanAccumulator
    from mergecraft.agents.gemini import _gemini_stream_event_handler

    handler, close_all = _gemini_stream_event_handler(tracer=tracer, model_id="gemini-2")
    acc = StreamSpanAccumulator(agent_name="gemini")
    handler(
        acc,
        {"type": "tool_use", "id": "tool-1", "name": "read_file", "input": {"p": _INPUT_MARKER}},
    )
    handler(acc, {"type": "tool_result", "tool_use_id": "tool-1", "output": _OUTPUT_MARKER})
    close_all()


_DRIVERS: dict[str, Callable[[Any], None]] = {"claude": _claude, "codex": _codex, "gemini": _gemini}


def _tool_spans(driver: str, *, trust_tier: str | None) -> list[Any]:
    from mergecraft.tracing import MemorySink, Tracer
    from mergecraft.tracing.review_context import ReviewContext, bind_review_context

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="payload-cap", run_id="payload-cap-run")
    if trust_tier is None:
        _DRIVERS[driver](tracer)
    else:
        with bind_review_context(ReviewContext(source="action", trust_tier=trust_tier)):
            _DRIVERS[driver](tracer)
    return [event for event in sink.events if event.kind.startswith("tool.")]


def _all_text(spans: list[Any]) -> str:
    return " ".join(repr(span.attrs) for span in spans)


@pytest.mark.parametrize("driver", sorted(_DRIVERS))
def test_untrusted_run_exports_no_tool_payload_bodies(driver: str) -> None:
    spans = _tool_spans(driver, trust_tier="untrusted")

    assert spans, f"{driver} emitted no tool spans"
    text = _all_text(spans)
    assert _INPUT_MARKER not in text
    assert _OUTPUT_MARKER not in text
    for span in spans:
        assert not set(TOOL_PAYLOAD_ATTRS) & set(span.attrs)


@pytest.mark.parametrize("driver", sorted(_DRIVERS))
def test_untrusted_run_keeps_payload_metadata(driver: str) -> None:
    spans = _tool_spans(driver, trust_tier="untrusted")
    call = next(span for span in spans if span.kind == "tool.call")

    hashed = {key: value for key, value in call.attrs.items() if key.endswith(".sha256")}
    assert hashed, f"{driver} tool.call carries no payload hash"
    for key, value in hashed.items():
        assert isinstance(value, str)
        assert len(value) == 64
        assert isinstance(call.attrs[key.removesuffix(".sha256") + ".bytes"], int)


def test_metadata_hash_covers_the_original_body() -> None:
    spans = _tool_spans("gemini", trust_tier="untrusted")
    call = next(span for span in spans if span.kind == "tool.call")

    assert call.attrs["tool.output.sha256"] == hashlib.sha256(_OUTPUT_MARKER.encode()).hexdigest()


@pytest.mark.parametrize("driver", sorted(_DRIVERS))
def test_trusted_run_keeps_tool_payload_bodies(driver: str) -> None:
    spans = _tool_spans(driver, trust_tier="trusted")

    assert _INPUT_MARKER in _all_text(spans)


def test_operator_opt_in_lifts_the_untrusted_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT", "true")

    spans = _tool_spans("claude", trust_tier="untrusted")

    assert _OUTPUT_MARKER in _all_text(spans)


def test_content_off_drops_payload_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERGECRAFT_TRACING_CONTENT", "off")

    spans = _tool_spans("claude", trust_tier="untrusted")
    call = next(span for span in spans if span.kind == "tool.call")

    assert not [key for key in call.attrs if key.endswith(".sha256")]
    assert _OUTPUT_MARKER not in _all_text(spans)


def test_pre_binding_untrusted_floor_applies_the_cap() -> None:
    """Before the resolved tier is stamped, the raw event floor decides."""
    from mergecraft.tracing import MemorySink, Tracer
    from mergecraft.tracing.review_context import ReviewContext, bind_review_context

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="payload-cap", run_id="payload-cap-run")
    context = ReviewContext(source="action", raw_event_trust_floor="untrusted")
    with bind_review_context(context):
        _claude(tracer)

    assert _OUTPUT_MARKER not in _all_text(list(sink.events))
