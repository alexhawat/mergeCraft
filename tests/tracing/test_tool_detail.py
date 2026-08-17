"""Tool-call detail enrichment — OB3.1 RED suite (part 4 of 4).

Wave plan: ``.ignorelocal/waves/04-observability-eval-wave-plan.md`` (PR OB3,
sub-wave OB3.1). Test-plan doc: ``docs/test-plans/04-observability-eval.md``.

Pins the OB3.2 File 3 additions to ``tracing/_tool_attrs.py``:

- ``gen_ai.tool.call.id`` correlation on BOTH sides — the shared helpers
  (``enrich_tool_request`` / ``enrich_tool_response``) gain a ``call_id``
  keyword so a tool row joins its request to its response (today only the
  driver call sites set it, each by hand).
- Duration: ``enrich_tool_response`` gains ``duration_ms`` → ``tool.duration_ms``.
- MCP-vs-native distinction: ``enrich_tool_request`` gains ``tool_origin``
  (``"mcp"`` / ``"native"``) → ``tool.origin``.

``test_existing_tool_attrs_unchanged`` is the regression pin and passes today:
called with the pre-OB3 signature, the helpers must keep emitting exactly the
attrs they always did (subset assertion — OB3.2 ADDS keys, it never renames or
revalues the existing ones).

The ``_tool_attrs`` module exists, so imports are top-level; the new keywords
do not, so the three addition tests fail RED (``TypeError``) under non-strict
``xfail`` (``green after OB3.2``) until OB3.2 lands.
"""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.tracing._tool_attrs import enrich_tool_request, enrich_tool_response


@pytest.fixture
def recording_sink() -> Any:
    """A real ``MemorySink`` wired into a fresh ``Tracer`` (house pattern)."""
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="tool-detail", run_id="tool-detail-run")
    return {"sink": sink, "tracer": tracer}


@pytest.mark.xfail(reason="green after OB3.2: call_id correlation on both sides", strict=False)
def test_tool_call_id_correlates_request_and_response(recording_sink: Any) -> None:
    """``gen_ai.tool.call.id`` is emitted by BOTH helpers, joining request to response."""
    tracer = recording_sink["tracer"]
    sink = recording_sink["sink"]

    with tracer.start_span("tool.call") as request_span:
        enrich_tool_request(request_span, arguments={"path": "a.py"}, call_id="call-42")
    with tracer.start_span("tool.call") as response_span:
        enrich_tool_response(response_span, output="contents", call_id="call-42")

    assert len(sink.events) == 2
    for event in sink.events:
        assert event.attrs["gen_ai.tool.call.id"] == "call-42", (
            f"the {event.kind} side must carry the correlating call id"
        )


@pytest.mark.xfail(reason="green after OB3.2: tool.call duration attr", strict=False)
def test_tool_call_records_duration(recording_sink: Any) -> None:
    """The close side records how long the tool call took."""
    tracer = recording_sink["tracer"]
    sink = recording_sink["sink"]

    with tracer.start_span("tool.call") as span:
        enrich_tool_response(span, output="done", duration_ms=87)

    assert sink.events[0].attrs["tool.duration_ms"] == 87


@pytest.mark.xfail(reason="green after OB3.2: MCP-vs-native distinction", strict=False)
def test_mcp_vs_native_tool_is_distinguished(recording_sink: Any) -> None:
    """A trace can tell an MCP-server tool call from a harness-native one."""
    tracer = recording_sink["tracer"]
    sink = recording_sink["sink"]

    with tracer.start_span("tool.call") as mcp_span:
        enrich_tool_request(mcp_span, arguments={"query": "q"}, tool_origin="mcp")
    with tracer.start_span("tool.call") as native_span:
        enrich_tool_request(native_span, arguments={"cmd": "ls"}, tool_origin="native")

    assert sink.events[0].attrs["tool.origin"] == "mcp"
    assert sink.events[1].attrs["tool.origin"] == "native"


def test_existing_tool_attrs_unchanged(recording_sink: Any) -> None:
    """Regression pin — pre-OB3 call signatures keep emitting the pre-OB3 attrs.

    OB3.2 ADDS optional keywords to the shared helpers; it must not rename,
    drop, or revalue the existing request/response attrs. Subset assertions
    (not exact key sets) so the new OB3.2 keys can land beside these. Passes
    today; must keep passing after OB3.2 — the one green pin of the OB3.1
    suite, no xfail.
    """
    tracer = recording_sink["tracer"]
    sink = recording_sink["sink"]

    with tracer.start_span("tool.call") as span:
        enrich_tool_request(span, arguments={"path": "a.py", "mode": "r"})
        enrich_tool_response(span, output="contents")

    attrs = sink.events[0].attrs
    # Open-side (request) attrs, unchanged.
    assert attrs["tool.arguments"] == {"path": "a.py", "mode": "r"}
    assert attrs["tool.argument_count"] == 2
    assert attrs["tool.input_keys"] == ["mode", "path"]
    assert attrs["tool.argument_bytes"] > 0
    assert attrs["tool.input_bytes"] == attrs["tool.argument_bytes"]
    # Close-side (response) attrs, unchanged.
    assert attrs["tool.exit_code"] == "ok"
    assert attrs["tool.result_kind"] == "text"
    assert attrs["tool.output"] == "contents"
    assert attrs["tool.result_bytes"] > 0
    assert attrs["gen_ai.tool.output"], "the GenAI dashboard row still gets a redacted body"

    with tracer.start_span("tool.call") as error_span:
        enrich_tool_response(error_span, output=None, error=ValueError("boom"))

    error_attrs = sink.events[1].attrs
    assert error_attrs["tool.exit_code"] == "error"
    assert error_attrs["tool.error_class"] == "ValueError"
    assert "boom" in error_attrs["tool.error_message"]
    assert error_attrs["gen_ai.tool.output"], "the failure path still feeds the GenAI row"
