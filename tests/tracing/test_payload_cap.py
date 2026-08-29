"""BR1.1 / BR2 — ``redact_tool_payload`` byte cap contracts (MCB-28)."""

from __future__ import annotations

from mergecraft.tracing.cap import TRACE_ATTRS_JSON_MAX_BYTES


def test_cap_is_bytes_not_characters() -> None:
    """MCB-28: cap compares UTF-8 byte length, not Python character count."""
    from mergecraft.tracing.redaction import redact_tool_payload

    # Each é is two UTF-8 bytes; 40_000 chars → 80_000 bytes (> 64 KiB cap).
    payload = "é" * 40_000
    redacted = redact_tool_payload(payload)
    assert len(redacted.encode("utf-8")) <= TRACE_ATTRS_JSON_MAX_BYTES


def test_oversize_payload_is_truncated_not_discarded() -> None:
    """MCB-28: slightly-over-cap payloads keep a head slice plus a marker."""
    from mergecraft.tracing.redaction import redact_tool_payload

    marker = "HEAD-MARKER-UNIQUE-01"
    tail = "TAIL-MARKER-UNIQUE-02"
    payload = marker + ("x" * TRACE_ATTRS_JSON_MAX_BYTES) + tail
    redacted = redact_tool_payload(payload)
    assert len(redacted.encode("utf-8")) <= TRACE_ATTRS_JSON_MAX_BYTES
    assert marker in redacted
    assert tail not in redacted
    assert "truncat" in redacted.casefold()
