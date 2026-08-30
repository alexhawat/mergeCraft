"""Driver-agnostic stream event rendering for operator logs (plan 13 W7).

Module: mergecraft.agents.stream_render
Depends: mergecraft.analyzers.redact, mergecraft.utils.bounded_text, loguru

Normalises Claude ``stream-json`` and Codex ``exec --json`` events into a
small canonical vocabulary, then renders one human-readable line per tool
interaction. Arguments and errors are truncated and redacted before emission.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.utils.bounded_text import truncate_text

_MAX_ARGS_CHARS = 120


def normalize_stream_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """Map a driver-shaped NDJSON event to a canonical render vocabulary.

    Returns ``None`` when the event should not produce an operator line.
    """
    event_type = str(event.get("type") or "")

    if event_type == "content_block_start":
        block = event.get("content_block")
        if isinstance(block, dict) and block.get("type") == "tool_use":
            arguments = block.get("input")
            return {
                "type": "tool_call",
                "name": str(block.get("name") or "tool"),
                "arguments": arguments if isinstance(arguments, dict) else {},
            }
        return None

    if event_type == "tool_result":
        return {
            "type": "tool_result",
            "name": str(event.get("name") or event.get("tool_use_id") or "tool"),
            "duration_ms": event.get("duration_ms"),
        }

    if event_type in {"tool_call", "tool_result", "tool_failure"}:
        return event

    if event_type == "item.started":
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "tool_call":
            arguments = item.get("input")
            return {
                "type": "tool_call",
                "name": str(item.get("name") or "tool"),
                "arguments": arguments if isinstance(arguments, dict) else {},
            }
        return None

    if event_type == "item.completed":
        item = event.get("item")
        if not isinstance(item, dict):
            return None
        item_type = item.get("type")
        if item_type == "tool_result":
            return {
                "type": "tool_result",
                "name": str(item.get("name") or item.get("tool_use_id") or "tool"),
                "duration_ms": item.get("duration_ms"),
            }
        if item_type == "tool_call":
            arguments = item.get("input")
            if isinstance(arguments, dict) and arguments:
                return {
                    "type": "tool_call",
                    "name": str(item.get("name") or "tool"),
                    "arguments": arguments,
                }
        return None

    if event_type in {"error", "turn.failed"}:
        payload = event.get("error")
        message = (
            payload.get("message")
            if isinstance(payload, dict)
            else (payload if isinstance(payload, str) else None)
        )
        if not message:
            message = event.get("message")
        tool_name = str(event.get("name") or event.get("tool") or "tool")
        return {
            "type": "tool_failure",
            "name": tool_name,
            "error": str(message or "unknown error"),
        }

    return None


def _format_arguments(arguments: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in arguments.items():
        if isinstance(value, (dict, list)):
            rendered = truncate_text(redact_secrets(json.dumps(value, default=str)))
        else:
            rendered = truncate_text(redact_secrets(str(value)))
        parts.append(f"{key}={rendered}")
    inner = ", ".join(parts)
    if len(inner) > _MAX_ARGS_CHARS:
        inner = truncate_text(inner, _MAX_ARGS_CHARS)
    return f"({inner})"


def _format_duration(duration_ms: Any) -> str | None:
    if not isinstance(duration_ms, (int, float)):
        return None
    ms = int(duration_ms)
    if ms < 1000:
        return f"{ms}ms"
    seconds = ms / 1000
    if seconds.is_integer():
        return f"{int(seconds)}s"
    return f"{seconds:.1f}s"


def render_stream_event(event: dict[str, Any]) -> str:
    """Render one canonical stream event as a single operator line."""
    event_type = str(event.get("type") or "")
    name = truncate_text(redact_secrets(str(event.get("name") or "tool")))

    if event_type == "tool_call":
        arguments = event.get("arguments")
        args = arguments if isinstance(arguments, dict) else {}
        suffix = _format_arguments(args) if args else ""
        return f"→ {name}{suffix}"

    if event_type == "tool_result":
        duration = _format_duration(event.get("duration_ms"))
        if duration is not None:
            return f"✓ {name} {duration}"
        return f"✓ {name}"

    if event_type == "tool_failure":
        error = truncate_text(redact_secrets(str(event.get("error") or "")))
        return f"✗ {name} {error}".rstrip()

    return ""


def emit_tool_failure_line(name: str, error: str) -> None:
    """Emit the canonical rendered failure line for a mediated tool error."""
    line = render_stream_event({"type": "tool_failure", "name": name, "error": error})
    if line:
        logger.info("{}", line)


def emit_rendered_stream_line(event: dict[str, Any]) -> None:
    """Normalise ``event`` and emit one rendered operator line when applicable."""
    normalized = normalize_stream_event(event)
    if normalized is None:
        return
    line = render_stream_event(normalized)
    if line:
        logger.info("{}", line)


__all__ = [
    "emit_rendered_stream_line",
    "emit_tool_failure_line",
    "normalize_stream_event",
    "render_stream_event",
]
