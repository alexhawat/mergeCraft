"""Shared tool-call attribute helpers (T1 + W4).

The three driver event handlers (``claude`` / ``codex`` / ``gemini``) and the
MCP ``tools/call`` handler all enrich a ``tool.call`` span with the same
request/response shape: byte counts, ``exit_code``, error class/message, and
the input-key list. ``KNOWN_VERB_TOOLS`` is the closed map of tool names that
emit a verb-specific child span (``tool.browse`` for ``browser``,
``tool.search`` for ``search``, …) on top of the parent ``tool.call``.

W4 splits the legacy single ``enrich_tool_call_attrs(span, *, arguments,
output, exit_code, error)`` helper (T1) into the open-side
``enrich_tool_request(span, *, arguments)`` and the close-side
``enrich_tool_response(span, *, output, error=None)`` — each call site
becomes one obvious line, the codex double-set bug is fixed, and the
MCP server's manual re-implementation lands on the same helper as the
three drivers (M1 / H2 / H3). The helpers live under ``tracing/`` so the
``mcp/`` package no longer reaches into ``agents/`` for them (H3).

Exports:
    KNOWN_VERB_TOOLS -- Map of tool name to verb sub-event kind.
    enrich_tool_request -- Open-side attrs (arguments, byte counts, input-keys).
    enrich_tool_response -- Close-side attrs (exit_code, output, error_class).
    emit_verb_subevent -- Open + immediately close a verb sub-event child span.
    _classify_tool_result -- Map a tool result value to a kind label.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.tracing.cap import TRACE_ATTRS_JSON_MAX_BYTES
from mergecraft.tracing.redaction import redact_tool_payload

if TYPE_CHECKING:
    from mergecraft.tracing.tracer import NullSpan, NullTracer, Span, Tracer


# Closed set of tool names that get a verb-specific child span alongside the
# parent ``tool.call``. The mapping is intentionally a dict, not a registry —
# the test surface (``test_known_verb_tool_emits_verb_sub_event``,
# ``test_unknown_verb_tool_emits_no_verb_sub_event``) treats it as exhaustive.
KNOWN_VERB_TOOLS: dict[str, str] = {
    "browser": "tool.browse",
    "search": "tool.search",
    "read_file": "tool.read",
    "write_file": "tool.write",
    "run_code": "tool.run_code",
    "load_tool": "tool.load_tool",
}


def _classify_tool_result(value: Any) -> str:
    """Classify a tool result value into a stable kind label.

    Labels:
        - ``"text"`` — ``str`` payloads (most common shape on every driver).
        - ``"json"`` — ``dict`` / ``list`` payloads (structured tool output).
        - ``"image"`` — ``bytes`` payloads whose header carries the PNG /
          JPEG magic number.
        - ``"list_of_blocks"`` — a ``list`` whose elements are ``dict``s
          (the Anthropic content-block shape that MCP ``ToolResult.content``
          also uses).
        - ``"unknown"`` — anything else; the row still carries the bytes
          count, but the kind is opaque.
    """
    if isinstance(value, str):
        return "text"
    if isinstance(value, bytes):
        # PNG: 89 50 4E 47 ; JPEG: FF D8 FF. Best-effort header sniff.
        if value.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")):
            return "image"
        return "unknown"
    if isinstance(value, dict):
        return "json"
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            return "list_of_blocks"
        return "json"
    return "unknown"


def _safe_json_bytes(value: Any) -> int:
    """Return the JSON-encoded byte count of ``value`` (best-effort)."""
    try:
        return len(json.dumps(value, default=str))
    except TypeError, ValueError:
        return len(str(value))


def enrich_tool_request(
    span: Span | NullSpan,
    *,
    arguments: Any,
    call_id: str | None = None,
    tool_origin: str | None = None,
) -> None:
    """Stamp the open-side ``tool.call`` attrs (request).

    Args:
        span: The ``Span`` to enrich. ``NullSpan.set_attribute`` is silently
            dropped so the disabled path is a true no-op.
        arguments: Raw arguments payload from the driver (dict for claude /
            gemini, string for codex). Sets ``tool.arguments`` /
            ``tool.argument_count`` / ``tool.argument_bytes`` /
            ``tool.input_bytes`` (always) and ``tool.input_keys`` (dict-only).
        call_id: Provider/harness tool-call id; emitted as
            ``gen_ai.tool.call.id`` so a tool row joins its request to its
            response (OB3). ``None`` emits nothing.
        tool_origin: ``"mcp"`` or ``"native"`` — whether the call went to
            the mergeCraft MCP server or stayed harness-native (OB3);
            emitted as ``tool.origin``. ``None`` emits nothing.
    """
    if call_id:
        span.set_attribute("gen_ai.tool.call.id", call_id)
    if tool_origin:
        span.set_attribute("tool.origin", tool_origin)
    if arguments is None:
        return
    arguments_bytes = _safe_json_bytes(arguments)
    span.set_attribute("tool.arguments", arguments)
    span.set_attribute(
        "tool.argument_count", len(arguments) if hasattr(arguments, "__len__") else 0
    )
    span.set_attribute("tool.argument_bytes", arguments_bytes)
    span.set_attribute("tool.input_bytes", arguments_bytes)
    if isinstance(arguments, dict):
        span.set_attribute("tool.input_keys", sorted(arguments.keys()))


def enrich_tool_response(
    span: Span | NullSpan,
    *,
    output: Any,
    error: BaseException | None = None,
    call_id: str | None = None,
    duration_ms: int | float | None = None,
) -> None:
    """Stamp the close-side ``tool.call`` attrs (response).

    Args:
        span: The ``Span`` to enrich. ``NullSpan.set_attribute`` is silently
            dropped so the disabled path is a true no-op.
        output: Tool result payload. Classified via ``_classify_tool_result``
            and JSON-encoded for the byte count.
        error: Exception instance for the failure path. ``type(error).__name__``
            is recorded as ``tool.error_class``; ``str(error)`` is redacted
            and capped as ``tool.error_message``; ``gen_ai.tool.output`` is
            still set so the GenAI dashboard sees the row.
        call_id: Provider/harness tool-call id; emitted as
            ``gen_ai.tool.call.id`` so the response joins its request (OB3).
            ``None`` emits nothing.
        duration_ms: Wall-clock duration of the tool call; emitted as
            ``tool.duration_ms`` (OB3). ``None`` emits nothing.
    """
    if call_id:
        span.set_attribute("gen_ai.tool.call.id", call_id)
    if duration_ms is not None:
        span.set_attribute("tool.duration_ms", duration_ms)
    if error is not None:
        span.set_attribute("tool.exit_code", "error")
        span.set_attribute("tool.error_class", type(error).__name__)
        from mergecraft.analyzers.redact import redact_secrets

        message = redact_secrets(str(error))[:TRACE_ATTRS_JSON_MAX_BYTES]
        span.set_attribute("tool.error_message", message)
        # Keep the GenAI conventions attr wired so the GenAI dashboard sees
        # the row even on the failure path.
        span.set_attribute("gen_ai.tool.output", redact_tool_payload(message))
        return

    # D9 / #296: classify ToolResult.is_error as error span (MCP always wraps).
    from mergecraft.mcp.shared import ToolResult

    if isinstance(output, ToolResult) and output.is_error:
        span.set_attribute("tool.exit_code", "error")
        span.set_attribute("tool.error_class", "ToolResult")
        span.set_status("error", "ToolResult.is_error=True")
        span.set_attribute("gen_ai.tool.output", redact_tool_payload(output))
        return

    span.set_attribute("tool.exit_code", "ok")
    if output is not None:
        output_bytes = _safe_json_bytes(output)
        kind = _classify_tool_result(output)
        span.set_attribute("tool.result_kind", kind)
        span.set_attribute("tool.result_bytes", output_bytes)
        span.set_attribute("tool.output_bytes", output_bytes)
        span.set_attribute("tool.output_kind", kind)
        span.set_attribute("tool.output", output)
        # The full payload is stringified + redacted for ``gen_ai.tool.output``
        # so the GenAI dashboard sees the body without leaking tokens. The
        # redactor caps at TRACE_ATTRS_JSON_MAX_BYTES already.
        span.set_attribute("gen_ai.tool.output", redact_tool_payload(output))


def emit_verb_subevent(
    tracer: Tracer | NullTracer | None,
    *,
    parent_span_id: str | None,
    tool_name: str,
    attrs: dict[str, Any] | None = None,
) -> None:
    """Open + immediately close a verb sub-event child span for known verbs.

    Args:
        tracer: The ``Tracer`` that owns the parent ``tool.call`` span.
            ``None`` (disabled tracing) or a ``NullTracer`` (the disabled
            surface ``get_tracer_from_settings`` returns) is a no-op.
        parent_span_id: The parent ``tool.call`` span's ``span_id``. Used as
            the new span's ``parent_span_id`` so Logfire's tree groups the
            verb row under the tool call.
        tool_name: The tool name from the driver event. Looked up against
            ``KNOWN_VERB_TOOLS``; tools outside the closed set emit no child
            span (``test_unknown_verb_tool_emits_no_verb_sub_event``).
        attrs: The parent ``tool.call`` span's attrs. Mirrored onto the child
            so Logfire's row inspector still has full context for each verb
            row — without it, the child row would be empty and the operator
            would have to click through to the parent.

    Returns:
        None. The child span is opened, decorated, and closed in one
        synchronous call. No new bookkeeping state is required — the span
        emits on close and is gone from the active-span stack by the time
        this function returns.
    """
    if tracer is None:
        return
    kind = KNOWN_VERB_TOOLS.get(tool_name)
    if kind is None:
        return
    try:
        child = tracer.start_span(kind, parent_span_id=parent_span_id)
        child.__enter__()
        if attrs:
            for key, value in attrs.items():
                try:
                    child.set_attribute(key, value)
                except Exception as attr_exc:  # pragma: no cover — defensive
                    logger.debug("verb sub-event attr {} failed: {}", key, attr_exc)
        # W4 / M6 — use ``Span.close`` so the end-time + active-context
        # reset happens in one place. The ``NullSpan`` surface inherits the
        # no-op behaviour from ``set_attribute`` / ``__exit__`` so the call
        # is tolerant of both.
        child.close()
    except Exception as exc:  # pragma: no cover — defensive
        # Tracing must never fail the run (#56 D6). A verb sub-event is
        # strictly informational; swallow any error so a malformed payload
        # cannot break the close path.
        logger.debug("verb sub-event {} for {} failed: {}", kind, tool_name, exc)


__all__ = [
    "KNOWN_VERB_TOOLS",
    "emit_verb_subevent",
    "enrich_tool_request",
    "enrich_tool_response",
]
