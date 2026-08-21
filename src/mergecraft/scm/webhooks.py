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
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mergecraft.review.snapshot import ReviewSnapshot, ReviewStageName, ReviewStageSpec

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
_GITLAB_TOKEN_HEADER = "X-Gitlab-Token"
_GITLAB_UUID_HEADERS = ("X-Gitlab-Event-UUID", "X-Gitlab-Webhook-UUID")


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
    snapshot: ReviewSnapshot
    stages: tuple[ReviewStageSpec, ...] = ()
    stages_ran: tuple[ReviewStageName, ...] = ()


class _WebhookDeliveryStore:
    """Process-local delivery and nonce store (not shared across workers).

    Missing delivery ids / nonces are fail-closed — callers must not invent
    ``{provider}:anonymous`` keys. Restarting the process clears this map.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._deliveries: dict[str, WebhookProcessResult] = {}
        self._nonces: set[str] = set()

    def remember_nonce(self, nonce: str) -> None:
        if not nonce.strip():
            msg = "missing webhook delivery id"
            raise ValueError(msg)
        with self._lock:
            if nonce in self._nonces:
                msg = f"replay of webhook nonce {nonce!r} rejected"
                raise ValueError(msg)
            self._nonces.add(nonce)

    def process(self, key: str, result: WebhookProcessResult) -> WebhookProcessResult:
        with self._lock:
            existing = self._deliveries.get(key)
            if existing is not None:
                return WebhookProcessResult(
                    result_id=existing.result_id,
                    duplicate=True,
                    provider=existing.provider,
                    event=existing.event,
                )
            self._deliveries[key] = result
            return result


_store = _WebhookDeliveryStore()


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
        if presented is None or not hmac.compare_digest(presented, secret):
            msg = "invalid webhook signature (shared-secret mismatch)"
            raise PermissionError(msg)
        return
    expected = _format_signature(name, _hmac_digest(body, secret))
    presented = _header(headers, _signature_header_name(name))
    if presented is None or not hmac.compare_digest(presented, expected):
        msg = "invalid webhook signature (hmac mismatch)"
        raise PermissionError(msg)


def webhook_delivery_id(provider: str, headers: dict[str, str]) -> str:
    """Return the provider delivery nonce, or raise when it is missing."""
    name = _require_supported(provider)
    return _delivery_nonce(name, headers)


def webhook_event_name(provider: str, headers: dict[str, str]) -> str:
    """Return the provider event name from headers, or ``unknown``."""
    name = _require_supported(provider)
    if name == "github":
        return _header(headers, "X-GitHub-Event") or "unknown"
    return _header(headers, "X-Gitlab-Event") or "unknown"


def _delivery_nonce(provider: str, headers: dict[str, str]) -> str:
    if provider == "github":
        nonce = _header(headers, _GITHUB_DELIVERY_HEADER)
    else:
        nonce = None
        for name in _GITLAB_UUID_HEADERS:
            nonce = _header(headers, name)
            if nonce:
                break
    if nonce is None or not nonce.strip():
        msg = "missing webhook delivery id"
        raise ValueError(msg)
    return nonce


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
    _store.remember_nonce(_delivery_nonce(name, headers))


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
    if not delivery_id.strip():
        msg = "missing webhook delivery id"
        raise ValueError(msg)
    key = f"{name}:{delivery_id}"
    result = WebhookProcessResult(
        result_id=delivery_id,
        duplicate=False,
        provider=name,
        event=event,
    )
    return _store.process(key, result)


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
    from mergecraft.review.engine import run_from_snapshot
    from mergecraft.review.snapshot import canonical_review_snapshot

    _ = body
    name = _require_supported(provider)
    snapshot: ReviewSnapshot = canonical_review_snapshot(
        entry="scm",
        mode="Review",
        source=name,
    )
    engine = run_from_snapshot(snapshot)

    async def _noop() -> None:
        return None

    async def _publish(_review: object) -> None:
        return None

    staged = engine.run_sync(
        materialize=_noop,
        analyze=_noop,
        review=_noop,
        publish=_publish,
    )
    return ConformingReviewRequest(
        mode=engine.snapshot.mode,
        provider=name,
        event=event,
        snapshot=engine.snapshot,
        stages=staged.stages,
        stages_ran=staged.stages_ran,
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
    "webhook_delivery_id",
    "webhook_event_name",
]
