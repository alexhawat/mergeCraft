"""RED contracts for #296 — ToolResult(is_error=True) → tool.exit_code=error.

W5 (Batch R RED): enrich_tool_response must classify ``output.is_error``
even when no Python exception is present, mapping it to the same error
attrs path that an explicit ``error=`` arg takes.

Bug (W0.4): ``_tool_attrs.py:174`` sets ``tool.exit_code=ok`` whenever
``error is None``; it never inspects ``getattr(output, "is_error", False)``.

Acceptance (after W6):
- A ``ToolResult(is_error=True)`` passed as ``output=`` → ``tool.exit_code=error``
  and span status ``"error"``.
- A ``ToolResult(is_error=False)`` (normal success) → ``tool.exit_code=ok``.
- A plain ``dict`` output (no ``is_error`` attribute) → ``tool.exit_code=ok``.
- ``gen_ai.tool.output`` is still set on the error path so the GenAI dashboard
  row exists.
- JSON-RPC remains unchanged; no ``mcp/server.py`` edits are required.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Minimal in-process Tracer + MemorySink
# ---------------------------------------------------------------------------


def _make_tracer() -> tuple[Any, Any]:
    """A real MemorySink wired into a fresh Tracer."""
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="is-error-test", run_id="is-error-run")
    return tracer, sink


def _events_by_kind(sink: Any) -> dict[str, list[Any]]:
    by_kind: dict[str, list[Any]] = {}
    for event in sink.events:
        kind = getattr(event, "kind", None)
        if isinstance(kind, str):
            by_kind.setdefault(kind, []).append(event)
    return by_kind


# ---------------------------------------------------------------------------
# W5.1 — ToolResult(is_error=True) must become tool.exit_code=error
# ---------------------------------------------------------------------------


def test_tool_result_is_error_true_sets_exit_code_error() -> None:
    """W5.1a — ToolResult(is_error=True) as output= → tool.exit_code=error.

    No Python exception is present; the error signal comes solely from
    ``output.is_error``.  enrich_tool_response must take the error attrs
    path (D9 / #296).
    """
    from mergecraft.mcp.shared import ToolResult
    from mergecraft.tracing._tool_attrs import enrich_tool_response

    tracer, sink = _make_tracer()

    with tracer.start_span("tool.call") as span:
        result = ToolResult(
            content=[{"type": "text", "text": "push is disabled"}],
            is_error=True,
        )
        enrich_tool_response(span, output=result)

    by_kind = _events_by_kind(sink)
    assert "tool.call" in by_kind, "no tool.call span emitted"
    tool_span = by_kind["tool.call"][0]

    assert tool_span.attrs.get("tool.exit_code") == "error", (
        f"expected tool.exit_code=error; got {tool_span.attrs.get('tool.exit_code')!r}"
    )
    assert tool_span.status == "error", f"expected span status=error; got {tool_span.status!r}"
    assert "gen_ai.tool.output" in tool_span.attrs, (
        "gen_ai.tool.output must be set even on is_error path so GenAI dashboard shows the row"
    )


def test_tool_result_is_error_false_stays_ok() -> None:
    """W5.1b — ToolResult(is_error=False) keeps tool.exit_code=ok.

    The default success path must be unaffected by the is_error check.
    """
    from mergecraft.mcp.shared import ToolResult
    from mergecraft.tracing._tool_attrs import enrich_tool_response

    tracer, sink = _make_tracer()

    with tracer.start_span("tool.call") as span:
        result = ToolResult(
            content=[{"type": "text", "text": "success"}],
            is_error=False,
        )
        enrich_tool_response(span, output=result)

    by_kind = _events_by_kind(sink)
    assert "tool.call" in by_kind
    tool_span = by_kind["tool.call"][0]

    assert tool_span.attrs.get("tool.exit_code") == "ok", (
        f"expected tool.exit_code=ok; got {tool_span.attrs.get('tool.exit_code')!r}"
    )


def test_plain_dict_output_stays_ok() -> None:
    """W5.1c — plain dict output (no is_error attr) → tool.exit_code=ok.

    Ensures the is_error check doesn't regress plain dict payloads.
    This test is NOT xfail — the current code already handles plain dicts
    correctly and must stay green.
    """
    from mergecraft.tracing._tool_attrs import enrich_tool_response

    tracer, sink = _make_tracer()

    with tracer.start_span("tool.call") as span:
        enrich_tool_response(span, output={"result": "ok"})

    by_kind = _events_by_kind(sink)
    assert "tool.call" in by_kind
    tool_span = by_kind["tool.call"][0]

    assert tool_span.attrs.get("tool.exit_code") == "ok"


def test_plain_dict_with_is_error_data_stays_ok() -> None:
    """Dict payloads carrying ``is_error`` as data must not be misclassified."""
    from mergecraft.tracing._tool_attrs import enrich_tool_response

    tracer, sink = _make_tracer()

    with tracer.start_span("tool.call") as span:
        enrich_tool_response(
            span,
            output={"is_error": True, "detail": "upstream reported a condition"},
        )

    by_kind = _events_by_kind(sink)
    tool_span = by_kind["tool.call"][0]
    assert tool_span.attrs.get("tool.exit_code") == "ok"
