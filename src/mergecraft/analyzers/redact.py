"""Secret redaction boundary for analyzer outputs (D8)."""

from __future__ import annotations

import hashlib
import json
import math
import re
from re import Pattern
from typing import Any

from loguru import logger

_REDACTED = "[REDACTED]"

_SECRET_PATTERNS: tuple[Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:xox[baprs]-)[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?([^\s'\"]{8,})", re.I),
)

_SECRET_KEY_RE = re.compile(
    r"^(?:api[_-]?key|secret|token|password|access[_-]?token|refresh[_-]?token|"
    r"id[_-]?token|bearer[_-]?token|auth[_-]?token|client[_-]?secret|private[_-]?key|"
    r"proxy[_-]?authorization|x[_-]?api[_-]?key|set[_-]?cookie|pat|passwd)$",
    re.IGNORECASE,
)

_MIN_ENTROPY_LENGTH = 16
_ENTROPY_RATIO = 0.85
_ENTROPY_TOKEN_RE = re.compile(r"[A-Za-z0-9+/=_-]{16,}")

_BENIGN_HEX_40_RE = re.compile(r"^[a-f0-9]{40}$")
_BENIGN_HEX_64_RE = re.compile(r"^[a-f0-9]{64}$")
_BENIGN_PURE_HEX_RE = re.compile(r"^[a-f0-9]+$")
_BENIGN_IDENTIFIER_RE = re.compile(r"^[a-z_]+$")


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


def _entropy_threshold(length: int) -> float:
    """Length-relative ceiling: max Shannon entropy for ``length`` distinct symbols."""
    return _ENTROPY_RATIO * math.log2(length)


def _is_benign_entropy_token(token: str) -> bool:
    if _BENIGN_PURE_HEX_RE.match(token):
        return _shannon_entropy(token) < _entropy_threshold(len(token))
    return False


def _should_force_redact_dense_token(token: str) -> bool:
    unique = len(set(token))
    if unique < 8 or len(token) >= 64:
        return False
    return unique / len(token) > 0.25


def _entropy_redact(text: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        token = match.group(0)
        if len(token) < _MIN_ENTROPY_LENGTH:
            return token
        if _BENIGN_HEX_40_RE.match(token) or _BENIGN_HEX_64_RE.match(token):
            return token
        if _BENIGN_IDENTIFIER_RE.match(token):
            return token
        if _should_force_redact_dense_token(token):
            return _REDACTED
        if _is_benign_entropy_token(token):
            return token
        if _shannon_entropy(token) >= _entropy_threshold(len(token)):
            return _REDACTED
        return token

    return _ENTROPY_TOKEN_RE.sub(replacer, text)


def _pattern_redact(text: str) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(_REDACTED, redacted)
    return redacted


def _maybe_redact_entire_string(text: str, redacted: str) -> str:
    """Redact credential-shaped single tokens that fall outside the ASCII entropy regex."""
    if redacted != text:
        return redacted
    if len(text) < _MIN_ENTROPY_LENGTH or any(char.isspace() for char in text):
        return redacted
    if _BENIGN_HEX_40_RE.match(text) or _BENIGN_HEX_64_RE.match(text):
        return redacted
    if _BENIGN_IDENTIFIER_RE.match(text):
        return redacted
    if _should_force_redact_dense_token(text):
        return _REDACTED
    if _is_benign_entropy_token(text):
        return redacted
    if len(set(text)) >= 8 and _shannon_entropy(text) >= _entropy_threshold(len(text)):
        return _REDACTED
    return redacted


def redact_secrets(text: str) -> str:
    """Redact secret-like values from arbitrary text by pattern and entropy."""
    if not text:
        return text
    redacted = _entropy_redact(_pattern_redact(text))
    return _maybe_redact_entire_string(text, redacted)


def _is_secret_json_key(key: str) -> bool:
    return bool(_SECRET_KEY_RE.match(key))


def _redact_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _REDACTED if _is_secret_json_key(str(key)) else _redact_json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_json_value(item) for item in value]
    if isinstance(value, str):
        return redact_secrets(value)
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _looks_like_jsonl(raw: str) -> bool:
    lines = [line for line in raw.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    for line in lines:
        try:
            json.loads(line)
        except json.JSONDecodeError:
            return False
    return True


def _redact_jsonl(raw: str) -> str:
    out_lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            out_lines.append(line)
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            out_lines.append(redact_secrets(line))
        else:
            out_lines.append(_json_dumps(_redact_json_value(payload)))
    suffix = "\n" if raw.endswith("\n") else ""
    return "\n".join(out_lines) + suffix


def _redact_json_text(raw: str) -> str | None:
    stripped = raw.strip()
    if not stripped:
        return raw
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        pass
    else:
        if isinstance(payload, (dict, list)):
            prefix = raw[: len(raw) - len(raw.lstrip())]
            suffix = raw[len(raw.rstrip()) :]
            return prefix + _json_dumps(_redact_json_value(payload)) + suffix

    decoder = json.JSONDecoder()
    index = 0
    length = len(raw)
    parts: list[str] = []
    found_json = False
    while index < length:
        char = raw[index]
        if char not in "{[":
            next_json = index
            while next_json < length and raw[next_json] not in "{[":
                next_json += 1
            parts.append(raw[index:next_json])
            index = next_json
            continue
        try:
            payload, end = decoder.raw_decode(raw, index)
        except json.JSONDecodeError:
            parts.append(raw[index])
            index += 1
            continue
        found_json = True
        parts.append(_json_dumps(_redact_json_value(payload)))
        index = end if end > index else index + 1
    if not found_json:
        return None
    return "".join(parts)


def redact_analyzer_output(raw: str, *, tool_id: str) -> str:
    """Redact analyzer stdout/stderr before any downstream consumer."""
    _ = tool_id
    if not raw:
        return raw
    stripped = raw.lstrip()
    if not stripped.startswith(("{", "[")):
        return redact_secrets(raw)
    if _looks_like_jsonl(raw):
        return _redact_jsonl(raw)
    redacted = _redact_json_text(raw)
    if redacted is not None:
        return redacted
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

    logger.configure(patcher=_patcher)  # type: ignore[arg-type]  # — loguru patcher stub is overly restrictive; _patcher(record) signature is compatible at runtime


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
