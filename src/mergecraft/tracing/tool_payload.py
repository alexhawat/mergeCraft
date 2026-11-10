"""Apply the content-capture level to tool span payload bodies at span close.

The claude, codex and gemini drivers and the MCP ``tools/call`` handler stamp
tool arguments and results on ``tool.*`` spans directly. Model payloads (prompt,
completion, reasoning) go through :func:`mergecraft.tracing.content.capture_text`;
this module gives tool payloads the same treatment from one place —
:meth:`mergecraft.tracing.tracer.Span.close` — so every driver is covered without
each call site having to remember the policy.

On a run whose bound review context reports a non-trusted tier, the effective
level is :func:`mergecraft.tracing.genai.resolve_capture_policy` for that tier
(the untrusted ``metadata`` cap, lifted only by an operator-owned
``exportUntrustedContent`` source). At ``metadata`` each body attribute is
replaced by ``<key>.bytes`` and ``<key>.sha256`` of the original; at ``off`` it
is dropped. Trusted runs, and spans closed with no review context bound, are
left unchanged.

Exports:
    TOOL_PAYLOAD_ATTRS: The span attributes that carry tool payload bodies.
    cap_tool_payload_attrs: Apply the run's capture level to a span's attrs.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final

from loguru import logger

__all__ = ["TOOL_PAYLOAD_ATTRS", "cap_tool_payload_attrs"]

TOOL_PAYLOAD_ATTRS: Final[tuple[str, ...]] = (
    "tool.arguments",
    "tool.input",
    "tool.output",
    "tool.error_message",
    "gen_ai.tool.input",
    "gen_ai.tool.output",
    "gen_ai.tool.call.arguments",
    "gen_ai.tool.call.result",
)


def _encoded(value: Any) -> bytes:
    """UTF-8 bytes of a payload value (strings verbatim, anything else as JSON)."""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace")
    try:
        text = json.dumps(value, default=str, sort_keys=True)
    except (TypeError, ValueError):
        text = str(value)
    return text.encode("utf-8", errors="replace")


def cap_tool_payload_attrs(attrs: dict[str, Any], *, trust_tier: str | None) -> dict[str, Any]:
    """Return ``attrs`` with tool payload bodies reduced to the run's capture level.

    Total and non-throwing: on any failure the bodies are dropped (fail closed)
    rather than exported.

    Args:
        attrs: The span's merged attributes.
        trust_tier: The run's trust tier from the bound review context, or
            ``None`` when no context is bound.

    Returns:
        dict[str, Any]: ``attrs`` unchanged, or a copy with bodies replaced.
    """
    if trust_tier is None or trust_tier == "trusted":
        return attrs
    present = [key for key in TOOL_PAYLOAD_ATTRS if key in attrs]
    if not present:
        return attrs
    try:
        from mergecraft.tracing.genai import resolve_capture_policy

        policy = resolve_capture_policy(trust_tier)
    except Exception as exc:
        logger.warning("tool payload capture policy failed; dropping bodies: {}", exc)
        policy = None
    if policy is not None and policy.emits_body:
        return attrs
    capped = dict(attrs)
    for key in present:
        value = capped.pop(key)
        if policy is None or not policy.emits_metadata:
            continue
        encoded = _encoded(value)
        capped[f"{key}.bytes"] = len(encoded)
        capped[f"{key}.sha256"] = hashlib.sha256(encoded).hexdigest()
    return capped
