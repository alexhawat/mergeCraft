"""Secret redaction boundary for analyzer outputs (D8)."""

from __future__ import annotations

import hashlib
import json
import math
import re
from re import Pattern
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.redaction_sentinel import REDACTION_SENTINEL
from mergecraft.redaction_structured import redact_structured_value

if TYPE_CHECKING:
    from collections.abc import Iterable

_SECRET_PATTERNS: tuple[Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:xox[baprs]-)[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?([^\s'\"]{8,})", re.I),
    re.compile(r"Basic [A-Za-z0-9+/=]{16,}"),
)

_MIN_ENTROPY_LENGTH = 16
_ENTROPY_RATIO = 0.85
_ENTROPY_TOKEN_RE = re.compile(r"[A-Za-z0-9+/=_-]{16,}")
_REPO_PATH_TOKEN_RE = re.compile(r"^[\w.-]+(?:/[\w.-]+)+$")

_BENIGN_HEX_40_RE = re.compile(r"^[a-f0-9]{40}$")
_BENIGN_HEX_64_RE = re.compile(r"^[a-f0-9]{64}$")
_BENIGN_PURE_HEX_RE = re.compile(r"^[a-f0-9]+$")
# Catalog identifiers only: snake_case, SCREAMING_SNAKE, and lowercase kebab.
# Mixed-case alphanumeric blobs (e.g. ``AbCdEfGh…``) are not identifiers and
# must fall through to the entropy pass. Plain lowercase/uppercase runs without
# ``_`` or ``-`` separators are not identifiers either. ``sk-…`` / ``ghp_…``
# still match ``_SECRET_PATTERNS`` first.
_BENIGN_IDENTIFIER_RE = re.compile(
    r"^(?:_[a-z][a-z0-9_]*|[a-z][a-z0-9]*(?:_[a-z0-9_]+)+"
    r"|[a-z][a-z0-9]*(?:-[a-z0-9]+)+|[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+"
    r"|[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+"  # RUSTSEC-2024-0001
    r"|[a-z][a-z0-9]*(?:[A-Z][a-z0-9]*)+)$"  # camelCase SARIF keys
)
_BENIGN_FILENAME_RE = re.compile(
    r"^[\w.-]+\.(?:txt|json|yaml|yml|sh|py|js|ts|md|toml|lock|html|proto)$"
)
_BENIGN_ISO_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?$")
_BENIGN_HTTP_URL_RE = re.compile(r"^https?://[\w.-]+(?::\d+)?(?:/[\w./#:?=&%+-]*)?$")
_LOWERCASE_SLUG_RE = re.compile(r"^[a-z]{12,24}$")
_SLUG_ENTROPY_SLACK = 0.12
# Analyzer metadata assignments (``catalog=unavailable``, ``status=skipped``) —
# exempt before the dense-token pass so glanceable catalog rows survive redaction.
_METADATA_ASSIGNMENT_RE = re.compile(r"^(?P<key>[a-z][a-z0-9_]*)=(?P<value>[a-z][a-z0-9_-]*)$")
_SIMPLE_METADATA_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


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


def _is_benign_filename(token: str) -> bool:
    """Common repo-relative filenames that are not credential material."""
    return _BENIGN_FILENAME_RE.fullmatch(token) is not None


def _is_benign_iso_timestamp(token: str) -> bool:
    """ISO-8601 UTC timestamps from analyzer reports (W6 #537 sweep)."""
    return _BENIGN_ISO_TIMESTAMP_RE.fullmatch(token) is not None


def _is_benign_http_url(token: str) -> bool:
    """Published http(s) links in analyzer output — not credential material."""
    return _BENIGN_HTTP_URL_RE.fullmatch(token) is not None


def _is_benign_lowercase_slug(token: str) -> bool:
    """Lowercase analyzer slugs without separators (W6 #537 sweep: ``psscriptanalyzer``)."""
    if _LOWERCASE_SLUG_RE.fullmatch(token) is None:
        return False
    threshold = _entropy_threshold(len(token)) + _SLUG_ENTROPY_SLACK
    return _shannon_entropy(token) <= threshold


def _is_benign_entropy_token(token: str) -> bool:
    if _BENIGN_PURE_HEX_RE.match(token):
        return _shannon_entropy(token) < _entropy_threshold(len(token))
    if _BENIGN_IDENTIFIER_RE.match(token):
        return True
    if _is_benign_filename(token):
        return True
    if _is_benign_iso_timestamp(token):
        return True
    if _is_benign_http_url(token):
        return True
    return _is_benign_lowercase_slug(token)


def _is_simple_metadata_token(token: str) -> bool:
    """Low-entropy catalog/status tokens in ``key=value`` metadata assignments."""
    if _BENIGN_IDENTIFIER_RE.match(token) is not None:
        return True
    if _SIMPLE_METADATA_TOKEN_RE.fullmatch(token) is None:
        return False
    if len(token) < _MIN_ENTROPY_LENGTH:
        return True
    if "_" in token or "-" in token:
        return True
    return _shannon_entropy(token) < _entropy_threshold(len(token))


def _is_benign_metadata_assignment(token: str) -> bool:
    """``key=value`` analyzer metadata where both sides are low-entropy identifiers."""
    match = _METADATA_ASSIGNMENT_RE.match(token)
    if match is None:
        return False
    key = match.group("key")
    value = match.group("value")
    return _is_simple_metadata_token(key) and _is_simple_metadata_token(value)


def _should_force_redact_dense_token(token: str) -> bool:
    unique = len(set(token))
    if unique < 8 or len(token) >= 64:
        return False
    return unique / len(token) > 0.25


def _looks_like_repo_path_token(token: str) -> bool:
    """Repo-relative path prefixes are not secrets — preserve for CI blame paths."""
    if "/" not in token or _REPO_PATH_TOKEN_RE.match(token) is None:
        return False
    segments = [segment for segment in token.split("/") if segment]
    if not segments or not all(re.search(r"[A-Za-z]", segment) for segment in segments):
        return False
    last = segments[-1]
    return "." in last or _is_benign_filename(token)


def _entropy_redact(text: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        token = match.group(0)
        if _looks_like_repo_path_token(token):
            return token
        if len(token) < _MIN_ENTROPY_LENGTH:
            return token
        if _BENIGN_HEX_40_RE.match(token) or _BENIGN_HEX_64_RE.match(token):
            return token
        if _BENIGN_IDENTIFIER_RE.match(token):
            return token
        if _is_benign_filename(token):
            return token
        if _is_benign_iso_timestamp(token):
            return token
        if _is_benign_http_url(token):
            return token
        if _is_benign_lowercase_slug(token):
            return token
        if _is_benign_metadata_assignment(token):
            return token
        if _should_force_redact_dense_token(token):
            return REDACTION_SENTINEL
        if _is_benign_entropy_token(token):
            return token
        if _shannon_entropy(token) >= _entropy_threshold(len(token)):
            return REDACTION_SENTINEL
        return token

    return _ENTROPY_TOKEN_RE.sub(replacer, text)


def _pattern_redact(text: str) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(REDACTION_SENTINEL, redacted)
    return redacted


def _maybe_redact_entire_string(text: str, redacted: str) -> str:
    """Redact credential-shaped single tokens that fall outside the ASCII entropy regex."""
    if redacted != text:
        return redacted
    if len(text) < _MIN_ENTROPY_LENGTH or any(char.isspace() for char in text):
        return redacted
    if _BENIGN_HEX_40_RE.match(text) or _BENIGN_HEX_64_RE.match(text):
        return redacted
    if _looks_like_repo_path_token(text):
        return redacted
    if _BENIGN_IDENTIFIER_RE.match(text):
        return redacted
    if _is_benign_filename(text):
        return redacted
    if _is_benign_iso_timestamp(text):
        return redacted
    if _is_benign_http_url(text):
        return redacted
    if _is_benign_lowercase_slug(text):
        return redacted
    if _is_benign_metadata_assignment(text):
        return redacted
    if _should_force_redact_dense_token(text):
        return REDACTION_SENTINEL
    if _is_benign_entropy_token(text):
        return redacted
    if len(set(text)) >= 8 and _shannon_entropy(text) >= _entropy_threshold(len(text)):
        return REDACTION_SENTINEL
    return redacted


def redact_secrets(text: str) -> str:
    """Redact secret-like values from arbitrary text by pattern and entropy."""
    if not text:
        return text
    redacted = _entropy_redact(_pattern_redact(text))
    return _maybe_redact_entire_string(text, redacted)


def _redact_json_value(value: Any) -> Any:
    return redact_structured_value(value, redact_string=redact_secrets)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _looks_like_jsonl(raw: str) -> bool:
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
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
    # Text between JSON documents is a secret carrier like any other. It used
    # to be copied through verbatim, so output that *began* with valid JSON --
    # which is what routes here at all -- returned its plaintext tail
    # unredacted: ``{"a":1} token=ghp_...`` leaked the token. Literal runs are
    # buffered and redacted as a unit rather than per slice, so a brace that
    # splits one run cannot split a secret out of the pattern's reach.
    literal: list[str] = []
    found_json = False

    def _flush_literal() -> None:
        if literal:
            parts.append(redact_secrets("".join(literal)))
            literal.clear()

    while index < length:
        char = raw[index]
        if char not in "{[":
            next_json = index
            while next_json < length and raw[next_json] not in "{[":
                next_json += 1
            literal.append(raw[index:next_json])
            index = next_json
            continue
        try:
            payload, end = decoder.raw_decode(raw, index)
        except json.JSONDecodeError:
            literal.append(raw[index])
            index += 1
            continue
        found_json = True
        _flush_literal()
        parts.append(_json_dumps(_redact_json_value(payload)))
        index = end if end > index else index + 1
    _flush_literal()
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


def _looks_like_secret_shape(token: str) -> bool:
    """True when ``token`` matches a known credential prefix or dense secret shape."""
    for pattern in _SECRET_PATTERNS:
        if pattern.search(token):
            return True
    if len(token) < _MIN_ENTROPY_LENGTH:
        return False
    if _looks_like_repo_path_token(token) or _is_benign_filename(token):
        return False
    if (
        _BENIGN_IDENTIFIER_RE.match(token)
        or _is_benign_lowercase_slug(token)
        or _is_benign_iso_timestamp(token)
        or _is_benign_http_url(token)
    ):
        return False
    if _BENIGN_HEX_40_RE.match(token) or _BENIGN_HEX_64_RE.match(token):
        return False
    if _is_benign_metadata_assignment(token):
        return False
    unique = len(set(token))
    if unique >= 8 and _shannon_entropy(token) >= _entropy_threshold(len(token)):
        return True
    return _should_force_redact_dense_token(token)


def _looks_like_benign_harmful_shape(token: str) -> bool:
    """True for analyzer-output tokens the W6 sweep proved lose operator signal when redacted."""
    if _looks_like_secret_shape(token):
        return False
    return (
        _BENIGN_IDENTIFIER_RE.match(token) is not None
        or _looks_like_repo_path_token(token)
        or _is_benign_filename(token)
        or _is_benign_iso_timestamp(token)
        or _is_benign_http_url(token)
        or _is_benign_lowercase_slug(token)
    )


def classify_entropy_redaction_hits(hits: Iterable[Any]) -> dict[str, list[dict[str, str]]]:
    """Classify entropy-sweep hits for operator review (wave 15 W6 / D13)."""
    secret_confirmed: list[dict[str, str]] = []
    benign_candidates: list[dict[str, str]] = []
    for hit in hits:
        token = str(getattr(hit, "token", ""))
        record = {
            "analyzer_id": str(getattr(hit, "analyzer_id", "")),
            "token": token,
            "context": str(getattr(hit, "context", "")),
        }
        if _looks_like_secret_shape(token):
            secret_confirmed.append(record)
        elif _looks_like_benign_harmful_shape(token):
            benign_candidates.append({**record, "classification": "benign_harmful_to_redact"})
    return {
        "benign_candidates": benign_candidates,
        "secret_confirmed": secret_confirmed,
    }


__all__ = [
    "assert_no_canary",
    "cache_key_fragment",
    "classify_entropy_redaction_hits",
    "install_loguru_redaction_filter",
    "redact_analyzer_output",
    "redact_for_fingerprint",
    "redact_log_message",
    "redact_secrets",
]
