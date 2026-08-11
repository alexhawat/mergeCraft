"""Shared tool-call attribute helpers (T1).

The three driver event handlers (``claude`` / ``codex`` / ``gemini``) and the
MCP ``tools/call`` handler all enrich a ``tool.call`` span with the same
request/response shape: byte counts, ``exit_code``, error class/message, and
the input-key list. ``KNOWN_VERB_TOOLS`` is the closed map of tool names that
emit a verb-specific child span (``tool.browse`` for ``browser``,
``tool.search`` for ``search``, …) on top of the parent ``tool.call``.

Keeping the helpers here means a new driver added later can reuse the same
shape without re-deriving the mapping — and Logfire's row inspector sees a
consistent attribute set across every emit site.

Exports:
    KNOWN_VERB_TOOLS -- Map of tool name to verb sub-event kind.
    enrich_tool_call_attrs -- Add request/response attrs to a span in one place.
    emit_verb_subevent -- Open + immediately close a verb sub-event child span.
    _classify_tool_result -- Map a tool result value to a kind label.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.tracing.cap import TRACE_ATTRS_JSON_MAX_BYTES
from mergecraft.tracing.tracer import Span

if TYPE_CHECKING:
    from mergecraft.tracing.tracer import NullTracer, Tracer


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


def enrich_tool_call_attrs(
    span: Span,
    *,
    arguments: Any = None,
    output: Any = None,
    exit_code: str = "ok",
    error: BaseException | None = None,
) -> None:
    """Add the T1 request/response attrs to a ``tool.call`` span.

    Args:
        span: The ``Span`` to enrich (must be a real ``Span``; ``NullSpan``
            is a no-op sink and ``set_attribute`` is silently dropped there).
        arguments: Raw arguments payload from the driver (dict for claude /
            gemini, string for codex). When ``None``, request-side attrs are
            skipped (already set by the open site, e.g. the MCP server sets
            them eagerly on the open-side and only needs the response-side
            attrs from this call).
        output: Tool result payload. Classified via ``_classify_tool_result``;
            its JSON-encoded size is recorded as ``tool.result_bytes`` /
            ``tool.output_bytes`` depending on which side the caller is
            stamping.
        exit_code: ``"ok"`` on success, ``"error"`` on failure. Always set
            so the row's GenAI dashboard surface stays consistent.
        error: Exception instance for the failure path. ``type(error).__name__``
            is recorded as ``tool.error_class``; ``str(error)`` is redacted
            and capped as ``tool.error_message``; ``gen_ai.tool.output`` is
            still set so the GenAI dashboard sees the row.
    """
    if arguments is not None:
        try:
            arguments_bytes = len(json.dumps(arguments, default=str))
        except TypeError, ValueError:
            arguments_bytes = len(str(arguments))
        span.set_attribute("tool.arguments", arguments)
        span.set_attribute(
            "tool.argument_count", len(arguments) if hasattr(arguments, "__len__") else 0
        )
        span.set_attribute("tool.argument_bytes", arguments_bytes)
        # Claude / codex / gemini drivers set ``tool.input`` / ``tool.output``
        # historically; keep them for the regression pin and add the
        # explicit-side attrs so Logfire's row inspector surfaces the
        # request/response split even when the driver uses a different name.
        if isinstance(arguments, dict):
            span.set_attribute("tool.input_keys", sorted(arguments.keys()))
            span.set_attribute("tool.input_bytes", arguments_bytes)
        else:
            # Codex / Gemini may carry a stringified input — the byte count
            # is still useful, but ``input_keys`` is dict-only.
            span.set_attribute("tool.input_bytes", arguments_bytes)

    if error is not None:
        span.set_attribute("tool.exit_code", "error")
        span.set_attribute("tool.error_class", type(error).__name__)
        # ``redact_secrets`` scrubs token-shaped substrings; the cap is the
        # existing TRACE_ATTRS_JSON_MAX_BYTES so a 1 MB exception traceback
        # does not blow past the JSONL ceiling.
        from mergecraft.analyzers.redact import redact_secrets

        message = redact_secrets(str(error))[:TRACE_ATTRS_JSON_MAX_BYTES]
        span.set_attribute("tool.error_message", message)
        # Keep the GenAI conventions attr wired so the GenAI dashboard sees
        # the row even on the failure path.
        from mergecraft.tracing.redaction import redact_tool_payload

        span.set_attribute("gen_ai.tool.output", redact_tool_payload(message))
        return

    span.set_attribute("tool.exit_code", exit_code)
    if output is not None:
        span.set_attribute("tool.result_kind", _classify_tool_result(output))
        try:
            output_bytes = len(json.dumps(output, default=str))
        except TypeError, ValueError:
            output_bytes = len(str(output))
        span.set_attribute("tool.result_bytes", output_bytes)
        span.set_attribute("tool.output_bytes", output_bytes)
        span.set_attribute("tool.output_kind", _classify_tool_result(output))
        span.set_attribute("tool.output", output)
        # The full payload is stringified + redacted for ``gen_ai.tool.output``
        # so the GenAI dashboard sees the body without leaking tokens. The
        # redactor caps at TRACE_ATTRS_JSON_MAX_BYTES already.
        from mergecraft.tracing.redaction import redact_tool_payload

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
        import time

        # ``ts_end_ns`` exists on real ``Span`` but not on ``NullSpan``;
        # the hasattr check keeps the call site tolerant of both — when
        # the disabled surface (``NullTracer`` → ``NullSpan``) is in use,
        # ``set_attribute`` is already a no-op and timing data is moot.
        if isinstance(child, Span):
            child.ts_end_ns = time.time_ns()
        child.__exit__(None, None, None)
    except Exception as exc:  # pragma: no cover — defensive
        # Tracing must never fail the run (#56 D6). A verb sub-event is
        # strictly informational; swallow any error so a malformed payload
        # cannot break the close path.
        logger.debug("verb sub-event {} for {} failed: {}", kind, tool_name, exc)


__all__ = [
    "KNOWN_VERB_TOOLS",
    "emit_verb_subevent",
    "enrich_tool_call_attrs",
]
