"""BR1.3 / BR4 — ``accept_webhook`` idempotency and replay store (MCB-13, D9/D10)."""

from __future__ import annotations

import time

import pytest

from mergecraft.scm.ingress import accept_webhook
from mergecraft.scm.webhooks import sign_webhook_payload

_SECRET = "br1-ingress-idempotency-secret"
_BODY = b'{"action":"opened"}'


def _github_headers(delivery_id: str) -> dict[str, str]:
    headers = sign_webhook_payload("github", body=_BODY, secret=_SECRET)
    headers["X-GitHub-Delivery"] = delivery_id
    headers["X-GitHub-Event"] = "pull_request"
    return headers


def test_redelivery_through_accept_webhook_is_a_duplicate() -> None:
    """D9: GitHub redelivery returns ``duplicate=True`` through ingress."""
    delivery_id = "br1-redelivery-canary-0001"
    headers = _github_headers(delivery_id)
    first = accept_webhook("github", headers=headers, body=_BODY, secret=_SECRET)
    assert first.duplicate is False
    second = accept_webhook("github", headers=headers, body=_BODY, secret=_SECRET)
    assert second.duplicate is True
    assert second.result_id == first.result_id


def test_replay_store_evicts_on_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCB-13: TTL eviction frees delivery ids after the replay window."""
    from mergecraft.scm import webhooks as webhooks_module

    monkeypatch.setattr(webhooks_module, "REPLAY_SKEW_SECONDS", 1)
    delivery_id = "br1-ttl-eviction-canary-0001"
    headers = _github_headers(delivery_id)
    accept_webhook("github", headers=headers, body=_BODY, secret=_SECRET)
    time.sleep(1.1)
    redelivery = accept_webhook("github", headers=headers, body=_BODY, secret=_SECRET)
    assert redelivery.duplicate is False


def test_replay_store_is_bounded() -> None:
    """MCB-13: the delivery store enforces a maximum entry count."""
    from mergecraft.scm import webhooks as webhooks_module

    max_entries = getattr(webhooks_module, "_MAX_DELIVERY_STORE_ENTRIES", None)
    if max_entries is None:
        pytest.fail("bounded delivery store constant is not defined yet (BR4)")
    assert isinstance(max_entries, int)
    assert max_entries > 0

    for index in range(max_entries + 5):
        delivery_id = f"br1-bounded-store-{index:04d}"
        headers = _github_headers(delivery_id)
        accept_webhook("github", headers=headers, body=_BODY, secret=_SECRET)

    store = webhooks_module._store
    with store._lock:
        delivery_count = len(store._deliveries)
        nonce_count = len(store._nonces)
    assert delivery_count <= max_entries
    assert nonce_count <= max_entries


def test_far_future_skew_is_rejected() -> None:
    """MCB-13: unsigned far-future skew must not bypass replay protection."""
    from mergecraft.scm.webhooks import reject_webhook_replay

    headers = _github_headers("br1-far-future-skew-0001")
    with pytest.raises(ValueError, match=r"stale webhook timestamp|skew"):
        reject_webhook_replay(
            "github",
            headers=headers,
            body=_BODY,
            received_at_skew_seconds=-86_400,
        )
