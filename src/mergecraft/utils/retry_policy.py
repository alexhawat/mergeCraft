"""Bounded, jittered, classification-driven HTTP retries (W9 / ``#34``).

Shared by ``utils.github.GitHubClient`` and
``integrations.cursor_cloud.client.CursorCloudClient``.

Contracts:
- Retryable: transport errors, HTTP 429, HTTP 5xx.
- Permanent: other 4xx and unrelated exceptions (pass through immediately).
- Safe methods (GET/HEAD/OPTIONS) may retry; mutations never retry blindly.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any, Final

import httpx
from tenacity import (
    RetryCallState,
    retry_base,
    stop_after_attempt,
    wait_exponential_jitter,
)

# Keep stop bound aligned with the GitHub client (≤5 attempts).
DEFAULT_STOP = stop_after_attempt(3)
DEFAULT_WAIT = wait_exponential_jitter(initial=0.5, max=8.0)

SAFE_HTTP_METHODS: Final[frozenset[str]] = frozenset({"GET", "HEAD", "OPTIONS"})

# CLI wrappers: treat these exit codes as rate-limit / overloaded (retryable
# for model-chain advance — never blindly re-issue a mutating CLI invoke).
RATE_LIMIT_EXIT_CODES: Final[frozenset[int]] = frozenset({429, 498})


def is_transient_http_error(exc: BaseException) -> bool:
    """True for transport failures and retryable HTTP statuses (429 / 5xx)."""
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code >= 500 or code == 429
    return False


def is_safe_http_method(method: str) -> bool:
    return method.strip().upper() in SAFE_HTTP_METHODS


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
_BILLING_MARKERS: Final[tuple[str, ...]] = ("credit", "balance", "billing")
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
) -> ProviderFailureClass:
    """Classify a provider refusal for failover — not GitHub HTTP retry.

    Structured JSON fields (statusCode, message) win. ``does not exist`` is
    consulted last and only together with HTTP 404 (unknown-model). Billing
    404s fail over. A structured JSON 404 that is not unknown-model fails
    over (D5). Unrelated unstructured 404s (missing asset / proxy) are
    permanent and do not advance the model chain.
    """
    payload = _provider_json_payload(stderr)
    haystack = f"{stderr} {_message_from_payload(payload)}".lower()
    http_404 = _is_http_404(stderr=stderr, status_code=status_code, payload=payload)
    billing = any(marker in haystack for marker in _BILLING_MARKERS)
    if billing:
        return ProviderFailureClass.BILLING
    if http_404 and _UNKNOWN_MODEL_MARKER in haystack:
        return ProviderFailureClass.UNKNOWN_MODEL
    if http_404 and payload is not None:
        return ProviderFailureClass.HTTP_404
    if http_404:
        return ProviderFailureClass.PERMANENT
    if any(needle in haystack for needle in _RETRYABLE_CLI_NEEDLES):
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
    if status_code is None:
        status_code = _status_code_from_payload(_provider_json_payload(stderr))
    kind = classify_provider_failure(stderr, status_code=status_code)
    return kind in _RETRYABLE_FAILURE_CLASSES


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


class retry_transient_safe_methods(retry_base):
    """Retry only when the HTTP method is safe **and** the error is transient."""

    def __call__(self, retry_state: RetryCallState) -> bool:
        if retry_state.outcome is None or not retry_state.outcome.failed:
            return False
        exc = retry_state.outcome.exception()
        if exc is None or not is_transient_http_error(exc):
            return False
        method = _http_method_from_retry_state(retry_state)
        if method is None:
            # Refuse to guess — missing method must not widen into a GET retry.
            return False
        return is_safe_http_method(method)


def _http_method_from_retry_state(retry_state: RetryCallState) -> str | None:
    """Resolve the HTTP method from kwargs (preferred) or positional ``args[1]``.

    Call sites must pass ``method`` as a kw-only argument (Cursor client) or as
    the first positional after ``self`` (GitHub client). No silent GET default.
    """
    if retry_state.kwargs and "method" in retry_state.kwargs:
        return str(retry_state.kwargs["method"])
    if retry_state.args and len(retry_state.args) >= 2:
        candidate = retry_state.args[1]
        if isinstance(candidate, str):
            return candidate
    return None


__all__ = [
    "DEFAULT_STOP",
    "DEFAULT_WAIT",
    "RATE_LIMIT_EXIT_CODES",
    "SAFE_HTTP_METHODS",
    "ProviderFailureClass",
    "classify_provider_failure",
    "is_retryable_cli_failure",
    "is_safe_http_method",
    "is_transient_http_error",
    "retry_transient_safe_methods",
]
