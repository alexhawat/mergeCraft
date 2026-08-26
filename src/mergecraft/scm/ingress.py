"""HTTP webhook ingress: authenticate, reject replays, then process (#361).

Deployment note: delivery-id dedup and replay rejection are process-local.
Multiple uvicorn/gunicorn workers or pod replicas do **not** share the store —
the same GitHub/GitLab delivery may be processed once per worker until the
process restarts. Use a single worker, sticky routing, or an external dedup
layer when duplicate review triggers are unacceptable.
"""

from __future__ import annotations

import json
from typing import Any

from mergecraft.scm.webhooks import (
    REPLAY_SKEW_SECONDS,
    WebhookProcessResult,
    process_webhook_event,
    reject_webhook_replay,
    verify_webhook_signature,
    webhook_delivery_id,
    webhook_event_name,
)


def accept_webhook(
    provider: str,
    *,
    headers: dict[str, str],
    body: bytes,
    secret: str,
    received_at_skew_seconds: int = 0,
) -> WebhookProcessResult:
    """Verify signature, then process the delivery with idempotency first.

    Call this at the HTTP ingress. Direct ``process_webhook_event`` helpers
    do not authenticate the request.

    Delivery-id dedup is process-local only: restarting the process clears the
    store, and multiple uvicorn workers do not share it. Neither GitHub nor
    GitLab sign a delivery timestamp in the webhook headers, so nonce reuse is
    not a freshness guarantee — only a per-process replay window keyed to
    ``REPLAY_SKEW_SECONDS``.
    """
    verify_webhook_signature(provider, headers=headers, body=body, secret=secret)
    if abs(received_at_skew_seconds) > REPLAY_SKEW_SECONDS:
        msg = f"stale webhook timestamp (skew {received_at_skew_seconds}s exceeds replay window)"
        raise ValueError(msg)
    delivery_id = webhook_delivery_id(provider, headers)
    event = webhook_event_name(provider, headers)
    payload: dict[str, Any]
    if not body.strip():
        payload = {}
    else:
        loaded = json.loads(body)
        if not isinstance(loaded, dict):
            msg = "webhook body must be a JSON object"
            raise ValueError(msg)
        payload = loaded
    result = process_webhook_event(
        provider,
        delivery_id=delivery_id,
        event=event,
        body=payload,
    )
    if result.duplicate:
        return result
    reject_webhook_replay(
        provider,
        headers=headers,
        body=body,
        received_at_skew_seconds=received_at_skew_seconds,
    )
    return result


__all__ = ["accept_webhook"]
