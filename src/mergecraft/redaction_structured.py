"""Shared structured redaction keys for analyzer, trace, and audit surfaces (MCB-30).

Leaf module: must not import from :mod:`mergecraft.tracing.redaction`,
:mod:`mergecraft.analyzers.redact`, or :mod:`mergecraft.enterprise.audit`.

Exports:
    DENY_KEYS -- attr/dict keys whose values are replaced wholesale.
    SECRET_KEY_RE -- regex matching credential-shaped JSON keys.
    is_secret_structured_key -- True when a key name must be redacted.
    redact_structured_value -- recursively redact dict/list/tuple values by key.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from mergecraft.redaction_sentinel import REDACTION_SENTINEL

if TYPE_CHECKING:
    from collections.abc import Callable

SECRET_KEY_RE = re.compile(
    r"^(?:api[_-]?key|secret|token|password|access[_-]?token|refresh[_-]?token|"
    r"id[_-]?token|bearer[_-]?token|auth[_-]?token|client[_-]?secret|private[_-]?key|"
    r"proxy[_-]?authorization|x[_-]?api[_-]?key|set[_-]?cookie|pat|passwd)$",
    re.IGNORECASE,
)

DENY_KEYS: tuple[str, ...] = (
    "authorization",
    "cookie",
    "api_key",
    "secret",
    "token",
    "password",
    "access_token",
    "refresh_token",
    "id_token",
    "bearer_token",
    "auth_token",
    "proxy_authorization",
    "x_api_key",
    "set_cookie",
    "private_key",
    "client_secret",
    "pat",
    "passwd",
)

_DENY_KEY_SET = frozenset(DENY_KEYS)


def _normalize_structured_key(key: str) -> str:
    return key.lower().replace("-", "_")


def is_secret_structured_key(key: str) -> bool:
    """Return whether ``key`` names a credential field in structured payloads."""
    normalized = _normalize_structured_key(key)
    if normalized in _DENY_KEY_SET:
        return True
    return bool(SECRET_KEY_RE.match(normalized))


def redact_structured_value(
    value: Any,
    *,
    redact_string: Callable[[str], str],
) -> Any:
    """Recursively redact structured values using ``redact_string`` for strings."""
    if isinstance(value, str):
        return redact_string(value)
    if isinstance(value, dict):
        return {
            key: REDACTION_SENTINEL
            if is_secret_structured_key(str(key))
            else redact_structured_value(item, redact_string=redact_string)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_structured_value(item, redact_string=redact_string) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_structured_value(item, redact_string=redact_string) for item in value)
    return value


__all__ = [
    "DENY_KEYS",
    "SECRET_KEY_RE",
    "is_secret_structured_key",
    "redact_structured_value",
]
