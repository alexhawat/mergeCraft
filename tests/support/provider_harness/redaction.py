"""Shared redaction helpers for provider-harness."""

from __future__ import annotations

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.tracing.redaction import redact_attrs


def sanitize_value(value: object) -> object:
    if isinstance(value, dict):
        redacted = redact_attrs({str(k): v for k, v in value.items()})
        return {k: sanitize_value(v) for k, v in redacted.items()}
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str):
        return redact_secrets(value)
    return value


def sanitize_json_text(value: object) -> str:
    sanitized = sanitize_value(value)
    if isinstance(sanitized, str):
        return sanitized
    import json

    return json.dumps(sanitized, sort_keys=True, default=str)
