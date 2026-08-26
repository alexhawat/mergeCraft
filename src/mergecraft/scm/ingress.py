"""HTTP webhook ingress: authenticate, reject replays, then process (#361)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol, cast

from mergecraft.scm.webhooks import (
    _MAX_REPLAY_SKEW_SECONDS,
    WebhookProcessResult,
    process_webhook_event,
    reject_webhook_replay,
    verify_webhook_signature,
    webhook_delivery_id,
    webhook_event_name,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    class _HttpxModelsLatin1Patch(Protocol):
        _normalize_header_value: Callable[[str | bytes, str | None], bytes]
        _mergecraft_latin1_patched: bool


def _install_httpx_latin1_header_values() -> None:
    """Match HTTP latin-1 header bytes when httpx builds TestClient requests."""
    import importlib

    for module_name in ("httpx._models", "httpx2._models"):
        try:
            httpx_models = importlib.import_module(module_name)
        except ImportError:
            continue
        if getattr(httpx_models, "_mergecraft_latin1_patched", False):
            continue

        def normalize(value: str | bytes, encoding: str | None = None) -> bytes:
            if isinstance(value, bytes):
                return value
            if not isinstance(value, str):
                msg = f"Header value must be str or bytes, not {type(value)}"
                raise TypeError(msg)
            if encoding is not None:
                return value.encode(encoding)
            try:
                return value.encode("ascii")
            except UnicodeEncodeError:
                return value.encode("latin-1")

        models = cast(  # importlib ModuleType lacks httpx private attrs
            "_HttpxModelsLatin1Patch", httpx_models
        )
        models._normalize_header_value = normalize
        models._mergecraft_latin1_patched = True


_install_httpx_latin1_header_values()


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
    ``_MAX_REPLAY_SKEW_SECONDS``.
    """
    verify_webhook_signature(provider, headers=headers, body=body, secret=secret)
    if abs(received_at_skew_seconds) > _MAX_REPLAY_SKEW_SECONDS:
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
