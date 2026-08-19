"""Normalize raw CI failures to a stable, redacted shape (K1.4 / K1.5)."""

from __future__ import annotations

import hashlib
import re
from typing import Any, cast

from mergecraft.analyzers.redact import redact_for_fingerprint, redact_secrets
from mergecraft.ci.types import NormalizedFailure, RawFailure

_TIMESTAMP_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s*")
_RUN_ID_TOKEN = re.compile(r"\b\d{10,}\b")
_ERROR_LINE = re.compile(
    r"(##\[error\][^\n]*|AssertionError[^\n]*|Error[^\n]*|FAIL(?:ED)?[^\n]*|"
    r"make: \*\*\*[^\n]*|Process completed with exit code [1-9]\d*)",
    re.I,
)


def _strip_run_noise(text: str) -> str:
    lines = []
    for line in text.splitlines():
        cleaned = _TIMESTAMP_PREFIX.sub("", line)
        cleaned = _RUN_ID_TOKEN.sub("<run-id>", cleaned)
        lines.append(cleaned.strip())
    return "\n".join(line for line in lines if line)


def _extract_error_signature(raw: RawFailure, log_excerpt: str) -> str:
    explicit = raw.get("error_signature")
    if explicit:
        return _strip_run_noise(str(explicit))
    for match in _ERROR_LINE.finditer(log_excerpt):
        candidate = _strip_run_noise(match.group(0))
        if candidate:
            return candidate
    tail = log_excerpt.strip().splitlines()
    return _strip_run_noise(tail[-1]) if tail else "unknown failure"


def _compute_fingerprint(*, command: str, error_signature: str) -> str:
    material = redact_for_fingerprint(f"{command.strip()}\0{error_signature.strip()}", tool_id="ci")
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def _coerce_exit_code(raw: RawFailure) -> int:
    value = raw.get("exit_code")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 1


def _coerce_artifacts(raw: RawFailure) -> list[str]:
    artifacts = raw.get("artifacts") or []
    if not isinstance(artifacts, list):
        return []
    return [redact_secrets(str(path)) for path in artifacts]


def normalize_failure(raw: dict[str, Any]) -> NormalizedFailure:
    """Normalize a raw provider failure to the K1.4 field table with ingest redaction."""
    typed = cast(  # raw is dict[str, Any]; cast to TypedDict for typed field access
        "RawFailure", raw
    )
    job = str(raw.get("job_name") or raw.get("job") or "unknown")
    step = str(raw.get("step_name") or raw.get("step") or "unknown")
    command = redact_secrets(str(raw.get("command") or ""))
    exit_code = _coerce_exit_code(typed)

    source_excerpt = str(raw.get("log_excerpt") or raw.get("log_text") or "")
    log_excerpt = redact_secrets(_strip_run_noise(source_excerpt))
    error_signature = _extract_error_signature(typed, log_excerpt)
    artifacts = _coerce_artifacts(typed)
    retry_state = raw.get("retry_state")
    if retry_state is not None:
        retry_state = str(retry_state)

    return NormalizedFailure(
        job=job,
        step=step,
        command=command,
        exit_code=exit_code,
        log_excerpt=log_excerpt,
        artifacts=artifacts,
        retry_state=retry_state,
        failure_fingerprint=_compute_fingerprint(command=command, error_signature=error_signature),
    )


__all__ = ["normalize_failure"]
