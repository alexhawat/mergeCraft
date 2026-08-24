"""Model-chain provider failure taxonomy (#466).

GitHub/HTTP retries (429/5xx, safe methods) live in ``retry_policy``. This
module classifies CLI/provider refusals so the model chain can fail over
without treating a billing 404 as ``schema_failure``.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any, Final

# CLI wrappers: treat these exit codes as rate-limit / overloaded (retryable
# for model-chain advance — never blindly re-issue a mutating CLI invoke).
RATE_LIMIT_EXIT_CODES: Final[frozenset[int]] = frozenset({429, 498})

# Provider prose for "not now". Two distinct classes, both retryable *for
# failover* — the chain's job is to reach a different model, not to re-issue
# against the one that just refused:
#   - rate limiting / overload: transient, the same provider may work later
#   - quota or credit exhaustion: not transient, but the next provider is
#     unaffected. Codex says "You've hit your usage limit", which matches none
#     of the rate-limit wording and so read as permanent (#446).
_RETRYABLE_CLI_NEEDLES: Final[tuple[str, ...]] = (
    "rate limit",
    "rate_limit",
    "too many requests",
    "overloaded",
    "429",
    "usage limit",
    "quota",
    "insufficient_quota",
)

# Billing *class* markers only — a generic HTTP 404 is retryable without them
# (#466). Do not grow this list as the sole classifier.
_BILLING_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:credits?|balance|billing)\b",
    re.IGNORECASE,
)
_UNKNOWN_MODEL_MARKER: Final[str] = "does not exist"
_HTTP_404_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:\bHTTP\s+404\b)|(?:\bstatusCode\s*[:=]\s*404\b)",
    re.IGNORECASE,
)


class ProviderFailureClass(StrEnum):
    """Distinct provider-failure classes for model-chain failover (#466)."""

    UNKNOWN_MODEL = "unknown_model"
    BILLING = "billing"
    HTTP_404 = "http_404"
    RETRYABLE = "retryable"
    PERMANENT = "permanent"


_RETRYABLE_FAILURE_CLASSES: Final[frozenset[ProviderFailureClass]] = frozenset(
    {
        ProviderFailureClass.BILLING,
        ProviderFailureClass.HTTP_404,
        ProviderFailureClass.RETRYABLE,
    }
)


def classify_provider_failure(
    stderr: str = "",
    *,
    status_code: int | None = None,
    payload: dict[str, Any] | None = None,
) -> ProviderFailureClass:
    """Classify a provider refusal for failover — not GitHub HTTP retry.

    Structured JSON fields (statusCode, message) win. ``does not exist`` is
    consulted last and only together with HTTP 404 (unknown-model). Billing
    404s fail over. A structured JSON 404 that is not unknown-model fails
    over (D5). Unrelated unstructured 404s (missing asset / proxy) are
    permanent and do not advance the model chain.
    """
    if payload is None:
        payload = _provider_json_payload(stderr)
    haystack = f"{stderr} {_message_from_payload(payload)}"
    http_404 = _is_http_404(stderr=stderr, status_code=status_code, payload=payload)
    if _looks_like_billing(stderr=haystack, payload=payload):
        return ProviderFailureClass.BILLING
    lowered = haystack.lower()
    if http_404 and _UNKNOWN_MODEL_MARKER in lowered:
        return ProviderFailureClass.UNKNOWN_MODEL
    if http_404 and payload is not None:
        return ProviderFailureClass.HTTP_404
    if http_404:
        return ProviderFailureClass.PERMANENT
    if any(needle in lowered for needle in _RETRYABLE_CLI_NEEDLES):
        return ProviderFailureClass.RETRYABLE
    return ProviderFailureClass.PERMANENT


def is_retryable_cli_failure(
    *,
    returncode: int | None,
    stderr: str = "",
    status_code: int | None = None,
) -> bool:
    """Classify CLI rate-limit / overload / quota / transient-404 failures as retryable."""
    if returncode is not None and returncode in RATE_LIMIT_EXIT_CODES:
        return True
    payload = _provider_json_payload(stderr)
    if status_code is None:
        status_code = _status_code_from_payload(payload)
    kind = classify_provider_failure(stderr, status_code=status_code, payload=payload)
    return kind in _RETRYABLE_FAILURE_CLASSES


def _looks_like_billing(
    *,
    stderr: str,
    payload: dict[str, Any] | None,
) -> bool:
    """True when structured fields or word-boundary billing tokens fire.

    Substring ``balance`` must not match ``load balancer``. Unrelated
    ``credit`` inside a longer token is ignored.
    """
    parts = [stderr, _message_from_payload(payload)]
    if payload is not None:
        for candidate in (payload, payload.get("data")):
            if not isinstance(candidate, dict):
                continue
            for key in ("code", "type", "error", "error_type", "reason"):
                value = candidate.get(key)
                if isinstance(value, str):
                    parts.append(value)
    return _BILLING_TOKEN_RE.search(" ".join(parts)) is not None


def _provider_json_payload(stderr: str) -> dict[str, Any] | None:
    text = stderr.strip()
    if not text:
        return None
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            continue
        return parsed if isinstance(parsed, dict) else None
    return None


def _message_from_payload(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return ""
    data = payload.get("data")
    if isinstance(data, dict):
        message = data.get("message")
        if isinstance(message, str):
            return message
    message = payload.get("message")
    return message if isinstance(message, str) else ""


def _status_code_from_payload(payload: dict[str, Any] | None) -> int | None:
    if payload is None:
        return None
    for candidate in (payload, payload.get("data")):
        if not isinstance(candidate, dict):
            continue
        code = candidate.get("statusCode")
        if isinstance(code, int):
            return code
    return None


def _is_http_404(
    *,
    stderr: str,
    status_code: int | None,
    payload: dict[str, Any] | None,
) -> bool:
    if status_code == 404:
        return True
    if _status_code_from_payload(payload) == 404:
        return True
    return _HTTP_404_RE.search(stderr) is not None


__all__ = [
    "RATE_LIMIT_EXIT_CODES",
    "ProviderFailureClass",
    "classify_provider_failure",
    "is_retryable_cli_failure",
]
