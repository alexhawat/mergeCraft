"""Bounded, jittered, classification-driven HTTP retries (W9 / ``#34``).

Shared by ``utils.github.GitHubClient`` and
``integrations.cursor_cloud.client.CursorCloudClient``.

Contracts:
- Retryable: transport errors, HTTP 429, HTTP 5xx.
- Permanent: other 4xx and unrelated exceptions (pass through immediately).
- Safe methods (GET/HEAD/OPTIONS) may retry; mutations never retry blindly.

Model-chain / Nous taxonomy lives in ``provider_failure`` — this module
must not own ``ProviderFailureClass`` or re-export its classifiers.
"""

from __future__ import annotations

from typing import Final

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
    "SAFE_HTTP_METHODS",
    "is_safe_http_method",
    "is_transient_http_error",
    "retry_transient_safe_methods",
]
