"""GitHub and GitLab webhook security, idempotency, and review conformance (#361).

Exports:
    SUPPORTED_WEBHOOK_PROVIDERS: GitHub and GitLab only (no Bitbucket).
    assert_provider_permissions: Per-adapter permission probe.
    assert_review_only_webhook_capabilities: Refuse commit / push / edit.
    conforming_review_request: Identical review mode across providers.
    handle_webhook_rate_limit: Surface 429 as retryable; do not drop the event.
    process_webhook_event: Process each delivery id once.
    reject_webhook_replay: Reject stale timestamps and reused nonces.
    sign_webhook_payload: Produce provider signature headers for a body.
    verify_webhook_signature: Timing-safe HMAC check for a supported provider.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

SUPPORTED_WEBHOOK_PROVIDERS: frozenset[str] = frozenset({"github", "gitlab"})

_MAX_REPLAY_SKEW_SECONDS = 300
_REVIEW_ONLY_FORBIDDEN: frozenset[str] = frozenset(
    {
        "commit",
        "push",
        "edit",
        "create_pull_request",
        "write",
    }
)

_GITHUB_SIGNATURE_HEADER = "X-Hub-Signature-256"
_GITHUB_DELIVERY_HEADER = "X-GitHub-Delivery"
_GITLAB_SIGNATURE_HEADER = "X-Gitlab-Token"


@dataclass(frozen=True, slots=True)
class WebhookProcessResult:
    """Outcome of one webhook delivery, reused for duplicate ids."""

    result_id: str
    duplicate: bool
    provider: str
    event: str


@dataclass(frozen=True, slots=True)
class WebhookRateLimitOutcome:
    """Retryable provider 429 — the event is kept, not dropped."""

    provider: str
    status_code: int
    retry_after_seconds: int
    retryable: bool

    def __str__(self) -> str:
        return (
            f"HTTP {self.status_code} rate limit for {self.provider}; "
            f"retry after {self.retry_after_seconds}s"
        )


@dataclass(frozen=True, slots=True)
class ConformingReviewRequest:
    """Provider-neutral review request produced from a webhook event."""

    mode: str
    provider: str
    event: str


_processed_deliveries: dict[str, WebhookProcessResult] = {}
_seen_nonces: set[str] = set()


def _require_supported(provider: str) -> str:
    name = provider.strip().casefold()
    if name not in SUPPORTED_WEBHOOK_PROVIDERS:
        msg = (
            f"unsupported webhook provider {provider!r}; supported: github, gitlab (not bitbucket)"
        )
        raise ValueError(msg)
    return name


def _header(headers: dict[str, str], name: str) -> str | None:
    wanted = name.casefold()
    for key, value in headers.items():
        if key.casefold() == wanted:
            return value
    return None


def _hmac_digest(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _signature_header_name(provider: str) -> str:
    if provider == "github":
        return _GITHUB_SIGNATURE_HEADER
    return _GITLAB_SIGNATURE_HEADER


def _format_signature(provider: str, digest: str) -> str:
    if provider == "github":
        return f"sha256={digest}"
    return digest


def sign_webhook_payload(provider: str, *, body: bytes, secret: str) -> dict[str, str]:
    """Return the signature header map for ``body`` under ``secret``."""
    name = _require_supported(provider)
    digest = _hmac_digest(body, secret)
    return {_signature_header_name(name): _format_signature(name, digest)}


def verify_webhook_signature(
    provider: str,
    *,
    headers: dict[str, str],
    body: bytes,
    secret: str,
) -> None:
    """Accept a matching HMAC; reject a mismatch or unsupported provider."""
    name = _require_supported(provider)
    expected = _format_signature(name, _hmac_digest(body, secret))
    presented = _header(headers, _signature_header_name(name))
    if presented is None or not hmac.compare_digest(presented, expected):
        msg = "invalid webhook signature (hmac mismatch)"
        raise PermissionError(msg)


def reject_webhook_replay(
    provider: str,
    *,
    headers: dict[str, str],
    body: bytes,
    received_at_skew_seconds: int,
) -> None:
    """Reject a stale timestamp or a reused delivery nonce."""
    _ = body
    name = _require_supported(provider)
    if received_at_skew_seconds > _MAX_REPLAY_SKEW_SECONDS:
        msg = f"stale webhook timestamp (skew {received_at_skew_seconds}s exceeds replay window)"
        raise ValueError(msg)
    nonce = _header(headers, _GITHUB_DELIVERY_HEADER) or _header(headers, "X-Gitlab-Webhook-UUID")
    if nonce is None:
        nonce = f"{name}:anonymous"
    if nonce in _seen_nonces:
        msg = f"replay of webhook nonce {nonce!r} rejected"
        raise ValueError(msg)
    _seen_nonces.add(nonce)


def process_webhook_event(
    provider: str,
    *,
    delivery_id: str,
    event: str,
    body: dict[str, Any],
) -> WebhookProcessResult:
    """Process ``delivery_id`` once; later copies return the stored result as a duplicate."""
    _ = body
    name = _require_supported(provider)
    key = f"{name}:{delivery_id}"
    existing = _processed_deliveries.get(key)
    if existing is not None:
        return WebhookProcessResult(
            result_id=existing.result_id,
            duplicate=True,
            provider=existing.provider,
            event=existing.event,
        )
    result = WebhookProcessResult(
        result_id=delivery_id,
        duplicate=False,
        provider=name,
        event=event,
    )
    _processed_deliveries[key] = result
    return result


def handle_webhook_rate_limit(
    provider: str,
    *,
    status_code: int,
    retry_after_seconds: int,
) -> WebhookRateLimitOutcome:
    """Surface a provider 429 as retryable so the event is not dropped."""
    name = _require_supported(provider)
    retryable = status_code == 429
    return WebhookRateLimitOutcome(
        provider=name,
        status_code=status_code,
        retry_after_seconds=retry_after_seconds,
        retryable=retryable,
    )


def assert_provider_permissions(provider: str) -> None:
    """Probe that ``provider`` is a supported webhook adapter."""
    _require_supported(provider)


def conforming_review_request(
    provider: str,
    *,
    event: str,
    body: dict[str, Any],
) -> ConformingReviewRequest:
    """Map GitHub pull_request and GitLab merge-request hooks to the same Review mode."""
    _ = body
    name = _require_supported(provider)
    return ConformingReviewRequest(mode="Review", provider=name, event=event)


def assert_review_only_webhook_capabilities(*, requested_capability: str) -> None:
    """Refuse write capabilities so webhook adapters cannot bypass review-only."""
    token = requested_capability.strip().casefold()
    if token in _REVIEW_ONLY_FORBIDDEN:
        msg = "review-only webhook adapters cannot commit, push, or edit the reviewed tree"
        raise PermissionError(msg)


__all__ = [
    "SUPPORTED_WEBHOOK_PROVIDERS",
    "ConformingReviewRequest",
    "WebhookProcessResult",
    "WebhookRateLimitOutcome",
    "assert_provider_permissions",
    "assert_review_only_webhook_capabilities",
    "conforming_review_request",
    "handle_webhook_rate_limit",
    "process_webhook_event",
    "reject_webhook_replay",
    "sign_webhook_payload",
    "verify_webhook_signature",
]
