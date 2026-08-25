"""RED contracts for enriched ``tool.call`` attrs (T1.1).

Wave: ``issues-tracing-sevn-quality`` / PR T1 — ``feat(tracing): enrich
tool.call attrs to carry invoke + complete + verb sub-event info``.

Contract
--------
The :class:`Tracer`-flushed ``tool.call`` span carries the request/response
byte counts, exit_code, error class/message, and the input-key list
sevn splits across ``tool.invoke`` / ``tool.complete``. Every emit site —
``mcp/server.py::tools/call`` plus the three agent drivers
(``claude`` / ``codex`` / ``gemini``) — must produce a span whose attrs
include the new keys D5 / T1.2 promises:

- ``tool.arguments`` (the raw arguments dict),
- ``tool.argument_count`` (length of the args dict),
- ``tool.argument_bytes`` (JSON-encoded arg bytes),
- ``tool.exit_code`` (``"ok"`` on success, ``"error"`` on failure),
- ``tool.result_kind`` / ``tool.result_bytes`` (claude / codex / gemini
  response side; the MCP server emits ``tool.result_kind`` /
  ``tool.result_bytes`` on success from ``tools/call``),
- ``tool.error_class`` / ``tool.error_message`` (redacted; set on
  failure),
- ``tool.output_bytes`` / ``tool.output_kind`` (driver close path),
- ``tool.input_bytes`` / ``tool.input_keys`` (driver open path).

Known-verb tools—``browser``, ``search``, ``read_file``, ``write_file``,
``run_code``, ``load_tool``—also emit a verb-named child span
(``tool.browse``, ``tool.search``, ``tool.read``, ``tool.write``,
``tool.run_code``, ``tool.load_tool``) opened on the tool_result-style
close event and closed immediately. Unknown-verb tools emit only the
parent ``tool.call`` with no child.

Two cross-cutting guarantees pin the new keys:

1. The 64 KiB cap on ``TraceEvent.attrs`` (``cap_event_attrs``) still
   applies — a 100 KB argument value collapses the attrs to
   ``{"truncated": True}`` so the row stays a single JSON line.
2. The existing redaction boundary scrubs ``Authorization: Bearer ghp_…``
   substrings so a token-shaped value embedded in the args cannot leak
   onto the span.

These tests are RED against the post-T3 + post-T2 tree (the ``trace_id``
plumbing and the ``provider.call`` parent are landed; T1.1 is the third
polish PR). The implementation did not exist at RED-suite time:

- ``src/mergecraft/mcp/server.py`` — ``call_attrs`` was not yet enriched
  with ``tool.arguments`` / ``argument_count`` / ``argument_bytes`` /
  ``exit_code`` / ``result_kind`` / ``result_bytes``; the failure path
  did not yet set ``tool.error_class``.
- ``src/mergecraft/agents/{claude,codex,gemini}.py`` — driver tool
  spans did not yet set ``tool.exit_code`` / input/output bytes /
  ``result_kind``.
- ``src/mergecraft/tracing/_tool_attrs.py`` — the shared
  ``KNOWN_VERB_TOOLS`` / ``enrich_tool_request`` /
  ``enrich_tool_response`` / ``emit_verb_subevent`` module was missing.
- ``src/mergecraft/tracing/redaction.py`` — ``redact_tool_payload``
  was missing.

Acceptance (as shipped): **11 collected; 11 green; 0 xfailed**. Test 6
(``test_known_verb_tool_emits_verb_sub_event``) is the verb-named
child-span (``tool.browse`` for ``tool.name == "browser"``) — was the
sole T1.2 xfail at RED-suite time and was reconciled by the T1
xfail-cleanup commit (``9021fd1``).
"""

from __future__ import annotations

from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Shared helpers — minimal tracer + sink fixtures, span-tree indexing.
# ---------------------------------------------------------------------------


def _events_by_kind(sink: Any) -> dict[str, list[Any]]:
    """Index ``sink.events`` by ``kind`` for O(1) span-tree assertions."""
    by_kind: dict[str, list[Any]] = {}
    for event in sink.events:
        by_kind.setdefault(event.kind, []).append(event)
    return by_kind


@pytest.fixture
def recording_sink() -> Any:
    """A real :class:`MemorySink` wired into a fresh :class:`Tracer`."""
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="tool-attrs", run_id="tool-attrs-run")
    return {"sink": sink, "tracer": tracer}


@pytest.fixture
def tool_call_spans(recording_sink: Any) -> list[Any]:
    """Every ``tool.call`` event recorded on the sink."""
    return _events_by_kind(recording_sink["sink"]).get("tool.call", [])


# ---------------------------------------------------------------------------
# Test 1 — ``mcp/server.py::tools/call`` success path adds the request/response
# attrs to the ``tool.call`` span.
# ---------------------------------------------------------------------------


def test_mcp_tool_call_span_has_request_attrs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful ``tools/call`` produces a ``tool.call`` span with the new request attrs.

    The plan's T1.1 test 1 — the MCP server's ``tools/call`` handler emits a
    ``tool.call`` span whose attrs include ``tool.arguments`` (the raw dict),
    ``tool.argument_count`` (its length), ``tool.argument_bytes``
    (JSON-encoded size), ``tool.exit_code="ok"`` (success marker),
    ``tool.result_kind`` (the classified result shape), and
    ``tool.result_bytes`` (the JSON-encoded result size). The new keys sit
    alongside the existing ``tool.name`` / ``tool.id`` / ``tool.server`` /
    ``gen_ai.*`` attrs (D5: additive, no removal).
    """
    from fastapi.testclient import TestClient

    from mergecraft.mcp.server import MCP_ENDPOINT, create_mcp_app
    from mergecraft.mcp.shared import ToolClass, ToolResult, ToolSpec
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="mcp-success", run_id="mcp-success-run")

    monkeypatch.setattr(
        "mergecraft.mcp.rpc.get_tracer_from_settings",
        lambda _settings: tracer,
    )

    async def _echo(arguments: Any) -> ToolResult:
        del arguments
        return ToolResult(content=[{"type": "text", "text": "echoed"}])

    spec = ToolSpec(
        name="echo",
        description="Echo a value back.",
        input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
        execute=_echo,
        tool_class=ToolClass.ANALYSIS,
    )
    client = TestClient(create_mcp_app([spec]))
    client.post(
        MCP_ENDPOINT, json={"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}}
    )
    client.post(MCP_ENDPOINT, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    response = client.post(
        MCP_ENDPOINT,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"q": "hello"}},
        },
    )
    assert response.status_code == 200
    assert response.json().get("result") is not None

    tool_calls = _events_by_kind(sink).get("tool.call", [])
    assert len(tool_calls) == 1, f"expected one tool.call span, got {len(tool_calls)}"
    attrs = tool_calls[0].attrs
    assert attrs["tool.name"] == "echo"
    assert attrs["tool.arguments"] == {"q": "hello"}
    assert attrs["tool.argument_count"] == 1
    assert isinstance(attrs["tool.argument_bytes"], int)
    assert attrs["tool.argument_bytes"] > 0
    assert attrs["tool.exit_code"] == "ok"
    assert attrs["tool.result_kind"] in {"text", "json", "image", "list_of_blocks", "unknown"}
    assert isinstance(attrs["tool.result_bytes"], int)
    assert attrs["tool.result_bytes"] > 0


# ---------------------------------------------------------------------------
# Test 2 — ``mcp/server.py::tools/call`` failure path adds the error attrs;
# ``gen_ai.tool.output`` still surfaces on the failed span.
# ---------------------------------------------------------------------------


def test_mcp_tool_call_span_has_error_attrs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing tool emits ``tool.exit_code="error"`` + ``tool.error_class`` / ``tool.error_message``.

    The plan's T1.1 test 2 — when ``tool.execute`` raises, the spanned
    ``tool.call`` must record ``tool.exit_code="error"``, the class name
    on ``tool.error_class``, a redacted message on ``tool.error_message``,
    and the existing ``gen_ai.tool.output`` attr so Logfire's GenAI
    dashboard still sees the row. ``gen_ai.tool.output`` was already
    emitted on the success path of the drivers; the failure path must
    keep it wired so the row stays on the same Logfire dashboard surface.
    """
    from fastapi.testclient import TestClient

    from mergecraft.mcp.server import MCP_ENDPOINT, create_mcp_app
    from mergecraft.mcp.shared import ToolClass, ToolResult, ToolSpec
    from mergecraft.tracing import MemorySink, Tracer

    class _BoomError(RuntimeError):
        """Distinguishable exception class so the attr assertion is exact."""

    async def _boom(_arguments: Any) -> ToolResult:
        raise _BoomError("tool kaboom: super-secret-ghp_abc1234567890123")

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="mcp-error", run_id="mcp-error-run")
    monkeypatch.setattr(
        "mergecraft.mcp.rpc.get_tracer_from_settings",
        lambda _settings: tracer,
    )

    spec = ToolSpec(
        name="boom",
        description="Always fails.",
        input_schema={"type": "object", "properties": {}},
        execute=_boom,
        tool_class=ToolClass.ANALYSIS,
    )
    # ``raise_server_exceptions=False`` so the TestClient surfaces the
    # tool's exception as a 500 rather than bubbling it through the test
    # — the span still emits on __exit__ with the error attrs set.
    client = TestClient(create_mcp_app([spec]), raise_server_exceptions=False)
    client.post(
        MCP_ENDPOINT, json={"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}}
    )
    client.post(MCP_ENDPOINT, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    response = client.post(
        MCP_ENDPOINT,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "boom", "arguments": {}},
        },
    )
    # The MCP handler re-raises the tool exception; the JSON-RPC layer
    # surfaces it as an internal error response. The span still emits on
    # __exit__ with the error attrs set.
    assert response.status_code == 500

    tool_calls = _events_by_kind(sink).get("tool.call", [])
    assert len(tool_calls) == 1
    attrs = tool_calls[0].attrs
    assert attrs["tool.exit_code"] == "error"
    assert attrs["tool.error_class"] == "_BoomError"
    assert isinstance(attrs["tool.error_message"], str)
    # The redacted message must not echo a bare ``ghp_…`` token; the
    # ANALYZER-SIDE redaction applies before the span hits the sink.
    assert "ghp_abc1234567890123" not in attrs["tool.error_message"]
    # Existing GenAI conventions attr stays set on the failure path.
    assert "gen_ai.tool.output" in attrs


# ---------------------------------------------------------------------------
# Test 3 — Claude ``tool_result`` close emits the tool-output attrs.
# ---------------------------------------------------------------------------


def test_claude_tool_call_span_has_request_response_attrs(
    recording_sink: Any,
) -> None:
    """Claude ``tool_result`` close emits ``tool.exit_code`` / ``tool.output_bytes`` / ``tool.output_kind``.

    The plan's T1.1 test 3 — the Claude driver's ``tool_result`` handler
    emits the new response-side attrs on the closing ``tool.call`` span.
    The fixture is the same ``content_block_start`` →
    ``tool_result`` event sequence ``tests/tracing/test_http_spans.py``
    uses for the anthropic provider test; we only assert the close-side
    attrs here.
    """
    from mergecraft.agents._stream_consumer import StreamSpanAccumulator
    from mergecraft.agents.claude import _claude_stream_event_handler

    tracer = recording_sink["tracer"]
    handler, close_all = _claude_stream_event_handler(
        tracer=tracer,
        parent_span_id=None,
        model_id="claude-sonnet-4",
    )
    acc = StreamSpanAccumulator(agent_name="claude")
    events: list[dict[str, Any]] = [
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "tool-claude-1",
                "name": "browser",
                "input": {"q": "claude-input"},
            },
        },
        {
            "type": "tool_result",
            "tool_use_id": "tool-claude-1",
            "content": "claude-output-text",
        },
    ]
    for event in events:
        handler(acc, event)
    close_all()

    tool_calls = _events_by_kind(recording_sink["sink"]).get("tool.call", [])
    assert len(tool_calls) == 1
    attrs = tool_calls[0].attrs
    assert attrs["tool.exit_code"] == "ok"
    assert isinstance(attrs["tool.output_bytes"], int)
    assert attrs["tool.output_bytes"] > 0
    assert attrs["tool.output_kind"] in {"text", "json", "image", "list_of_blocks", "unknown"}


# ---------------------------------------------------------------------------
# Test 4 — Codex ``item.completed`` close emits the same response attrs.
# ---------------------------------------------------------------------------


def test_codex_tool_call_span_has_request_response_attrs(
    recording_sink: Any,
) -> None:
    """Codex ``item.completed`` close emits ``tool.exit_code`` / ``tool.output_bytes`` / ``tool.output_kind``.

    The plan's T1.1 test 4 — codex's ``item.completed`` handler closes
    the matching ``tool.call`` span and now also sets the new response
    attrs on close. The fixture opens a tool.call on ``item.started``
    and closes it on the matching ``item.completed`` with ``type ==
    "function_call"``; the assertions target the close-side attrs only.
    """
    from mergecraft.agents._stream_consumer import StreamSpanAccumulator
    from mergecraft.agents.codex_stream import codex_stream_event_handler

    tracer = recording_sink["tracer"]
    handler, close_all = codex_stream_event_handler(
        tracer=tracer,
        model_id="codex-mini",
    )
    acc = StreamSpanAccumulator(agent_name="codex")
    events: list[dict[str, Any]] = [
        {
            "type": "item.started",
            "item": {
                "type": "tool_call",
                "id": "tool-codex-1",
                "name": "browser",
                "input": "codex-input",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "type": "tool_call",
                "id": "tool-codex-1",
                "name": "browser",
                "input": "codex-input",
            },
        },
    ]
    for event in events:
        handler(acc, event)
    close_all()

    tool_calls = _events_by_kind(recording_sink["sink"]).get("tool.call", [])
    assert len(tool_calls) == 1
    attrs = tool_calls[0].attrs
    assert attrs["tool.exit_code"] == "ok"
    assert isinstance(attrs["tool.output_bytes"], int)
    assert attrs["tool.output_bytes"] > 0
    assert attrs["tool.output_kind"] in {"text", "json", "image", "list_of_blocks", "unknown"}


# ---------------------------------------------------------------------------
# Test 5 — Gemini ``tool_result`` close emits the same response attrs.
# ---------------------------------------------------------------------------


def test_gemini_tool_call_span_has_request_response_attrs(
    recording_sink: Any,
) -> None:
    """Gemini ``tool_result`` close emits the same request/response attrs.

    The plan's T1.1 test 5 — the gemini driver emits the new close-side
    attrs from its ``tool_result`` handler. The fixture opens a tool.call
    on the ``tool_use`` event and closes it on the matching
    ``tool_result`` event.
    """
    from mergecraft.agents._stream_consumer import StreamSpanAccumulator
    from mergecraft.agents.gemini import _gemini_stream_event_handler

    tracer = recording_sink["tracer"]
    handler, close_all = _gemini_stream_event_handler(
        tracer=tracer,
        model_id="gemini-2",
    )
    acc = StreamSpanAccumulator(agent_name="gemini")
    events: list[dict[str, Any]] = [
        {
            "type": "tool_use",
            "id": "tool-gemini-1",
            "name": "browser",
            "input": {"q": "gemini-input"},
        },
        {
            "type": "tool_result",
            "tool_use_id": "tool-gemini-1",
            "output": "gemini-output-text",
        },
    ]
    for event in events:
        handler(acc, event)
    close_all()

    tool_calls = _events_by_kind(recording_sink["sink"]).get("tool.call", [])
    assert len(tool_calls) == 1
    attrs = tool_calls[0].attrs
    assert attrs["tool.exit_code"] == "ok"
    assert isinstance(attrs["tool.output_bytes"], int)
    assert attrs["tool.output_bytes"] > 0
    assert attrs["tool.output_kind"] in {"text", "json", "image", "list_of_blocks", "unknown"}


# ---------------------------------------------------------------------------
# Test 6 — known-verb tool ``browser`` emits a ``tool.browse`` child span.
# T1.2 made this deterministic; xfail marker removed post-merge.
# ---------------------------------------------------------------------------


def test_known_verb_tool_emits_verb_sub_event(recording_sink: Any) -> None:
    """``tool.name == "browser"`` → child ``tool.complete`` span with ``kind="tool.browse"``.

    The plan's T1.1 test 6 — the closed ``tool.call`` span is the
    parent of a verb-specific child span whose ``kind`` matches the
    ``KNOWN_VERB_TOOLS`` mapping (``browser`` → ``tool.browse``). The
    child span opens on the close event and closes immediately; its
    attrs mirror the parent so Logfire's row inspector still has full
    context. This is the **T1.2 GREEN-only surface** — the verb
    sub-event emission is the differentiating feature; the parent
    ``tool.call`` span's enriched attrs land on T1.2 too, but every
    other test in this suite already pins those.
    """
    from mergecraft.agents._stream_consumer import StreamSpanAccumulator
    from mergecraft.agents.claude import _claude_stream_event_handler

    tracer = recording_sink["tracer"]
    handler, close_all = _claude_stream_event_handler(
        tracer=tracer,
        parent_span_id=None,
        model_id="claude-sonnet-4",
    )
    acc = StreamSpanAccumulator(agent_name="claude")
    events: list[dict[str, Any]] = [
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "tool-browser-1",
                "name": "browser",
                "input": {"q": "browse"},
            },
        },
        {
            "type": "tool_result",
            "tool_use_id": "tool-browser-1",
            "content": "ok",
        },
    ]
    for event in events:
        handler(acc, event)
    close_all()

    by_kind = _events_by_kind(recording_sink["sink"])
    tool_calls = by_kind.get("tool.call", [])
    browse_children = by_kind.get("tool.browse", [])
    assert len(tool_calls) == 1
    assert len(browse_children) == 1, "expected one tool.browse child span for tool.name=='browser'"
    assert browse_children[0].parent_span_id == tool_calls[0].span_id
    assert browse_children[0].attrs["tool.name"] == "browser"


# ---------------------------------------------------------------------------
# Test 7 — unknown-verb tool ``frobnicate`` emits no child span.
# ---------------------------------------------------------------------------


def test_unknown_verb_tool_emits_no_verb_sub_event(recording_sink: Any) -> None:
    """``tool.name == "frobnicate"`` → only the parent ``tool.call``; no child.

    The plan's T1.1 test 7 — the verb sub-event emission is gated on
    membership in the closed ``KNOWN_VERB_TOOLS`` set. Tools outside
    the closed set (a hypothetical ``frobnicate``) emit only the
    parent ``tool.call`` span with no child — Logfire's tree groups
    the parent row under the standard ``tool.call`` kind only.
    """
    from mergecraft.agents._stream_consumer import StreamSpanAccumulator
    from mergecraft.agents.claude import _claude_stream_event_handler

    tracer = recording_sink["tracer"]
    handler, close_all = _claude_stream_event_handler(
        tracer=tracer,
        parent_span_id=None,
        model_id="claude-sonnet-4",
    )
    acc = StreamSpanAccumulator(agent_name="claude")
    events: list[dict[str, Any]] = [
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "tool-frob-1",
                "name": "frobnicate",
                "input": {"q": "frob"},
            },
        },
        {
            "type": "tool_result",
            "tool_use_id": "tool-frob-1",
            "content": "ok",
        },
    ]
    for event in events:
        handler(acc, event)
    close_all()

    by_kind = _events_by_kind(recording_sink["sink"])
    # Only the parent ``tool.call`` span — no ``tool.frobnicate`` child
    # (the closed ``KNOWN_VERB_TOOLS`` set strips the verb emission).
    assert len(by_kind.get("tool.call", [])) == 1
    child_kinds = [kind for kind in by_kind if kind != "tool.call"]
    assert child_kinds == []


# ---------------------------------------------------------------------------
# Test 8 — 100 KB argument value → ``attrs={"truncated": True}`` via
# ``cap_event_attrs`` (D8 / convention 8).
# ---------------------------------------------------------------------------


def test_tool_arguments_capped_at_64kb(
    recording_sink: Any,
) -> None:
    """A 100 KB argument value collapses ``attrs`` to ``{"truncated": True}``.

    The plan's T1.1 test 8 — the 64 KiB cap on ``TraceEvent.attrs``
    (T2 / D8, ``TRACE_ATTRS_JSON_MAX_BYTES`` at ``tracing/cap.py:18``)
    must wrap the new ``tool.arguments`` / ``tool.argument_bytes`` /
    ``tool.output`` attrs so a 100 KB argument does not blow past the
    per-row JSONL ceiling. The cap is per-string-value: a 100 KB string
    value replaces the rows ``attrs`` with ``{"truncated": True}`` so
    the row survives on disk as a single JSON line. The new
    ``tool.arguments`` attr must therefore be stored as a string (not a
    raw dict) so the existing cap path can detect it.
    """
    big_payload = "x" * 100_000  # 100 KB — comfortably past the 64 KiB cap
    tracer = recording_sink["tracer"]
    with tracer.start_span("tool.call") as span:
        span.set_attribute("tool.name", "browser")
        span.set_attribute("tool.arguments", big_payload)

    tool_calls = _events_by_kind(recording_sink["sink"]).get("tool.call", [])
    assert len(tool_calls) == 1
    assert tool_calls[0].attrs == {"truncated": True}


# ---------------------------------------------------------------------------
# Test 9 — ``Authorization: Bearer ghp_…`` substring in args is redacted.
# ---------------------------------------------------------------------------


def test_tool_arguments_redact_secrets(
    recording_sink: Any,
) -> None:
    """An ``Authorization: Bearer ghp_…`` substring in args is scrubbed before reach the sink.

    The plan's T1.1 test 9 — the existing redaction boundary
    (tracing/redaction.py: ``redact_attrs`` + analyzer ``redact_secrets``)
    scrubs token-shaped substrings from any string value inside
    ``attrs``. The new ``tool.arguments`` attr inherits that boundary
    automatically — a ``Authorization: Bearer ghp_…`` substring must
    not leak onto the span.
    """
    tracer = recording_sink["tracer"]
    secret = "Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz123456"
    with tracer.start_span("tool.call") as span:
        span.set_attribute("tool.name", "browser")
        span.set_attribute("tool.arguments", {"header": secret})

    tool_calls = _events_by_kind(recording_sink["sink"]).get("tool.call", [])
    assert len(tool_calls) == 1
    attrs = tool_calls[0].attrs
    # The bare token substring must not survive redaction.
    serialized = str(attrs)
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in serialized
    # The other argument value is preserved (only the secret substring is masked).
    assert attrs["tool.arguments"]["header"] != secret
    assert "Authorization" in attrs["tool.arguments"]["header"]


# ---------------------------------------------------------------------------
# Test 10 — the existing ``tool.call`` attrs are still present (regression pin).
# ---------------------------------------------------------------------------


def test_existing_tool_call_attrs_still_present(recording_sink: Any) -> None:
    """The existing ``tool.name`` / ``tool.id`` / ``tool.server`` / ``gen_ai.*`` attrs remain.

    The plan's T1.1 test 10 — D5 is "additive, no removal". The existing
    fixture shape (the ``tool.name`` / ``tool.id`` / ``tool.server`` /
    ``gen_ai.operation.name`` / ``gen_ai.tool.name`` / ``gen_ai.tool.call.id``
    attrs) must remain on the span after T1.2 lands, so the enrichments
    are a strict superset of the prior surface.
    """
    tracer = recording_sink["tracer"]
    with tracer.start_span("tool.call") as span:
        span.set_attribute("tool.name", "checkout_pr")
        span.set_attribute("tool.id", "call-existing-1")
        span.set_attribute("tool.server", "mergecraft")
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", "checkout_pr")
        span.set_attribute("gen_ai.tool.call.id", "call-existing-1")

    tool_calls = _events_by_kind(recording_sink["sink"]).get("tool.call", [])
    assert len(tool_calls) == 1
    attrs = tool_calls[0].attrs
    assert attrs["tool.name"] == "checkout_pr"
    assert attrs["tool.id"] == "call-existing-1"
    assert attrs["tool.server"] == "mergecraft"
    assert attrs["gen_ai.operation.name"] == "execute_tool"
    assert attrs["gen_ai.tool.name"] == "checkout_pr"
    assert attrs["gen_ai.tool.call.id"] == "call-existing-1"


# ---------------------------------------------------------------------------
# Test 11 — the disabled tracing path is a true no-op (convention 9 / #56 D9).
# ---------------------------------------------------------------------------


def test_disabled_tracer_path_emits_no_tool_call_attrs() -> None:
    """``NullTracer`` returns ``NullSpan``; no attrs are threaded, no exception raised.

    The plan's T1.1 test 11 — the disabled path is a no-op. The
    ``NullTracer`` is what ``get_tracer_from_settings`` returns when
    tracing is disabled; ``start_span`` returns a ``NullSpan`` whose
    ``set_attribute`` is a no-op. The existing surface is preserved —
    no ``AttributeError`` is raised when a code path calls
    ``span.set_attribute("tool.exit_code", "ok")`` on a ``NullSpan``.
    """
    from mergecraft.tracing import NullTracer

    null = NullTracer()
    with null.start_span("tool.call") as span:
        span.set_attribute("tool.name", "browser")
        span.set_attribute("tool.exit_code", "ok")
        span.set_attribute("tool.output_bytes", 42)


__all__ = [
    "test_claude_tool_call_span_has_request_response_attrs",
    "test_codex_tool_call_span_has_request_response_attrs",
    "test_disabled_tracer_path_emits_no_tool_call_attrs",
    "test_existing_tool_call_attrs_still_present",
    "test_gemini_tool_call_span_has_request_response_attrs",
    "test_known_verb_tool_emits_verb_sub_event",
    "test_mcp_tool_call_span_has_error_attrs",
    "test_mcp_tool_call_span_has_request_attrs",
    "test_tool_arguments_capped_at_64kb",
    "test_tool_arguments_redact_secrets",
    "test_unknown_verb_tool_emits_no_verb_sub_event",
]
