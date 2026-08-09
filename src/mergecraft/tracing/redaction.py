"""Redaction layer for ``TraceEvent.attrs`` (D7).

Builds on the existing helpers in :mod:`mergecraft.analyzers.redact` and
:mod:`mergecraft.utils.secrets` — no second matcher is implemented here. The
tracing-specific additions are:

1. A deny-key list — any attr whose key (case-insensitive) appears here has
   its value replaced with the literal ``"[REDACTED]"``.
2. The deny-value patterns ``ghp_*`` / ``sk-*`` already match inside
   :func:`mergecraft.analyzers.redact.redact_secrets`; this module applies
   the existing helper to every string value (recursively into nested
   dicts and lists) so a ``ghp_…`` or ``sk-…`` substring cannot escape.

Exports:
    DENY_KEYS -- tuple of attr keys whose values are dropped wholesale.
    redact_attrs -- recursively redact an ``attrs`` dict, returning a new dict.
    redact_event -- return a deep-copied ``TraceEvent`` with redacted attrs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.redact import redact_secrets

if TYPE_CHECKING:
    from mergecraft.tracing.event import TraceEvent

DENY_KEYS: tuple[str, ...] = (
    "authorization",
    "cookie",
    "api_key",
    "secret",
    "password",
    "access_token",
    "refresh_token",
    "id_token",
    "bearer_token",
    "auth_token",
)

_REDACTED = "[REDACTED]"


def _redact_value(value: Any) -> Any:
    """Recursively redact a value: strings via the shared helper, structures recursively."""
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {key: _redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    return value


def redact_attrs(attrs: dict[str, Any] | None) -> dict[str, Any]:
    """Return a redacted copy of ``attrs`` (never the input dict)."""
    if not attrs:
        return {}
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        if key.lower() in DENY_KEYS:
            out[key] = _REDACTED
            continue
        out[key] = _redact_value(value)
    return out


def redact_event(event: TraceEvent) -> TraceEvent:
    """Return a deep-copied :class:`TraceEvent` with redacted ``attrs``."""
    return event.model_copy(update={"attrs": redact_attrs(event.attrs)})


__all__ = ["DENY_KEYS", "redact_attrs", "redact_event"]
