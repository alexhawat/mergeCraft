"""HTTP webhook ingress: authenticate, reject replays, then process (#361)."""

from __future__ import annotations

import json
from typing import Any

from mergecraft.scm.webhooks import (
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
    """Verify signature and replay protection, then process the delivery.

    Call this at the HTTP ingress. Direct ``process_webhook_event`` helpers
    do not authenticate the request.
    """
    verify_webhook_signature(provider, headers=headers, body=body, secret=secret)
    reject_webhook_replay(
        provider,
        headers=headers,
        body=body,
        received_at_skew_seconds=received_at_skew_seconds,
    )
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
    return process_webhook_event(
        provider,
        delivery_id=delivery_id,
        event=event,
        body=payload,
    )


__all__ = ["accept_webhook"]
