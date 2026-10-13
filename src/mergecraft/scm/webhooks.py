"""GitHub and GitLab webhook security and review conformance (#361).

Exports:
    SUPPORTED_WEBHOOK_PROVIDERS: GitHub and GitLab only (no Bitbucket).
    assert_provider_permissions: Per-adapter permission probe.
    assert_review_only_webhook_capabilities: Refuse commit / push / edit.
    conforming_review_request: Identical review mode across providers.
    handle_webhook_rate_limit: Surface 429 as retryable; do not drop the event.
    sign_webhook_payload: Produce provider signature headers for a body.
    verify_webhook_signature: Timing-safe HMAC check for a supported provider.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mergecraft.review.snapshot import ReviewSnapshot, ReviewStageName, ReviewStageSpec

SUPPORTED_WEBHOOK_PROVIDERS: frozenset[str] = frozenset({"github", "gitlab"})

_MAX_SIGNATURE_HEADER_BYTES = 8192
_SIGNATURE_HEADER_TOO_LONG_MSG = "webhook signature/header exceeds maximum length"

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
_GITLAB_TOKEN_HEADER = "X-Gitlab-Token"


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
    snapshot: ReviewSnapshot
    stages: tuple[ReviewStageSpec, ...] = ()
    stages_ran: tuple[ReviewStageName, ...] = ()


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
    return _GITLAB_TOKEN_HEADER


def _format_signature(provider: str, digest: str) -> str:
    if provider == "github":
        return f"sha256={digest}"
    return digest


def _reject_overlong_signature_value(value: str) -> None:
    if len(value.encode("utf-8", "surrogateescape")) > _MAX_SIGNATURE_HEADER_BYTES:
        raise PermissionError(_SIGNATURE_HEADER_TOO_LONG_MSG)


def _timing_safe_compare(left: str, right: str) -> bool:
    _reject_overlong_signature_value(left)
    _reject_overlong_signature_value(right)
    return hmac.compare_digest(
        left.encode("utf-8", "surrogateescape"),
        right.encode("utf-8", "surrogateescape"),
    )


def sign_webhook_payload(provider: str, *, body: bytes, secret: str) -> dict[str, str]:
    """Return the signature header map for ``body`` under ``secret``.

    GitHub uses HMAC-SHA256 of the body. GitLab's ``X-Gitlab-Token`` is a
    shared-secret equality check, not an HMAC of the body.
    """
    name = _require_supported(provider)
    if name == "gitlab":
        return {_GITLAB_TOKEN_HEADER: secret}
    digest = _hmac_digest(body, secret)
    return {_signature_header_name(name): _format_signature(name, digest)}


def verify_webhook_signature(
    provider: str,
    *,
    headers: dict[str, str],
    body: bytes,
    secret: str,
) -> None:
    """Accept a matching GitHub HMAC or GitLab shared secret; reject otherwise."""
    if not secret.strip():
        msg = "missing webhook secret"
        raise PermissionError(msg)
    name = _require_supported(provider)
    if name == "gitlab":
        presented = _header(headers, _GITLAB_TOKEN_HEADER)
        if presented is None or not _timing_safe_compare(presented, secret):
            msg = "invalid webhook signature (shared-secret mismatch)"
            raise PermissionError(msg)
        return
    expected = _format_signature(name, _hmac_digest(body, secret))
    presented = _header(headers, _signature_header_name(name))
    if presented is None or not _timing_safe_compare(presented, expected):
        msg = "invalid webhook signature (hmac mismatch)"
        raise PermissionError(msg)


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
    from mergecraft.review.snapshot import canonical_review_snapshot

    _ = body
    name = _require_supported(provider)
    snapshot: ReviewSnapshot = canonical_review_snapshot(
        entry="scm",
        mode="Review",
        source=name,
    )
    return ConformingReviewRequest(
        mode=snapshot.mode,
        provider=name,
        event=event,
        snapshot=snapshot,
        stages=snapshot.stages,
        stages_ran=(),
    )


def assert_review_only_webhook_capabilities(*, requested_capability: str) -> None:
    """Refuse write capabilities so webhook adapters cannot bypass review-only."""
    token = requested_capability.strip().casefold()
    if token in _REVIEW_ONLY_FORBIDDEN:
        msg = "review-only webhook adapters cannot commit, push, or edit the reviewed tree"
        raise PermissionError(msg)


__all__ = [
    "SUPPORTED_WEBHOOK_PROVIDERS",
    "ConformingReviewRequest",
    "WebhookRateLimitOutcome",
    "assert_provider_permissions",
    "assert_review_only_webhook_capabilities",
    "conforming_review_request",
    "handle_webhook_rate_limit",
    "sign_webhook_payload",
    "verify_webhook_signature",
]
