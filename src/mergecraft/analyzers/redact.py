"""Secret redaction boundary for analyzer outputs (D8)."""

from __future__ import annotations

import hashlib
import math
import re
from re import Pattern

from loguru import logger

_REDACTED = "[REDACTED]"

_SECRET_PATTERNS: tuple[Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:xox[baprs]-)[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?([^\s'\"]{8,})", re.I),
)

_MIN_ENTROPY_LENGTH = 20
_ENTROPY_THRESHOLD = 4.0


def _shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    length = len(value)
    entropy = 0.0
    for count in counts.values():
        probability = count / length
        entropy -= probability * math.log2(probability)
    return entropy


def _entropy_redact(text: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        token = match.group(0)
        if len(token) < _MIN_ENTROPY_LENGTH:
            return token
        if _shannon_entropy(token) >= _ENTROPY_THRESHOLD:
            return _REDACTED
        return token

    return re.sub(r"[A-Za-z0-9+/=_-]{20,}", replacer, text)


def _pattern_redact(text: str) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(_REDACTED, redacted)
    return redacted


def redact_secrets(text: str) -> str:
    """Redact secret-like values from arbitrary text by pattern and entropy."""
    if not text:
        return text
    return _entropy_redact(_pattern_redact(text))


def redact_analyzer_output(raw: str, *, tool_id: str) -> str:
    """Redact analyzer stdout/stderr before any downstream consumer."""
    _ = tool_id
    return redact_secrets(raw)


def redact_for_fingerprint(body: str, *, tool_id: str) -> str:
    """Redact text that feeds finding fingerprint inputs."""
    _ = tool_id
    return redact_secrets(body)


def cache_key_fragment(material: str, *, tool_id: str) -> str:
    """Return a cache-key fragment with secrets removed."""
    _ = tool_id
    return hashlib.sha256(redact_secrets(material).encode()).hexdigest()


def redact_log_message(message: str) -> str:
    """Filter hook for loguru sinks."""
    if isinstance(message, str):
        return redact_secrets(message)
    return str(message)


def install_loguru_redaction_filter() -> None:
    """Attach a loguru patcher that redacts secret values from all log records."""

    def _patcher(record: dict[str, object]) -> None:
        record["message"] = redact_log_message(str(record["message"]))

    logger.configure(patcher=_patcher)  # type: ignore[arg-type]


def assert_no_canary(text: str, canary: str) -> None:
    """Test hook: raise when a planted canary secret appears in output material."""
    if canary in text:
        msg = "canary secret escaped the redaction boundary"
        raise AssertionError(msg)


__all__ = [
    "assert_no_canary",
    "cache_key_fragment",
    "install_loguru_redaction_filter",
    "redact_analyzer_output",
    "redact_for_fingerprint",
    "redact_log_message",
    "redact_secrets",
]
