"""Shared structured redaction keys for analyzer, trace, and audit surfaces (MCB-30).

Leaf module: must not import from :mod:`mergecraft.tracing.redaction`,
:mod:`mergecraft.analyzers.redact`, or :mod:`mergecraft.enterprise.audit`.

Exports:
    DENY_KEYS -- attr/dict keys whose values are replaced wholesale.
    SECRET_KEY_RE -- regex matching credential-shaped JSON keys.
    is_credential_key_name -- the one key-name rule shared with the env filter.
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

# A key whose last word is one of these names a credential: ``DB_PASSWORD``,
# ``webhook_secret``, ``session_cookie``, ``GITHUB_TOKEN``, ``clientSecret``.
# The plural ``credentials`` is left out: ``GOOGLE_APPLICATION_CREDENTIALS``
# is a file path the provider env passes through by name.
_CREDENTIAL_LAST_WORDS = frozenset(
    {
        "apikey",
        "cookie",
        "credential",
        "passphrase",
        "passwd",
        "password",
        "secret",
        "token",
    }
)
# ``key`` alone is too common (``cache_key``, ``sort_key``, ``correlation_key``);
# it names a credential only after one of these qualifiers (``OPENAI_API_KEY``,
# ``aws_secret_access_key``, ``private_key``).
_CREDENTIAL_KEY_QUALIFIERS = frozenset(
    {
        "access",
        "account",
        "api",
        "auth",
        "client",
        "deploy",
        "encryption",
        "license",
        "master",
        "private",
        "secret",
        "session",
        "signing",
        "ssh",
        "subscription",
    }
)
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_KEY_WORD_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def _normalize_structured_key(key: str) -> str:
    return key.lower().replace("-", "_")


def _key_words(key: str) -> list[str]:
    """``OPENAI_API_KEY`` / ``clientSecret`` / ``x-api-key`` -> lowercase words."""
    spaced = _CAMEL_BOUNDARY_RE.sub("_", key)
    return [word for word in _KEY_WORD_SPLIT_RE.split(spaced.lower()) if word]


def is_credential_key_name(key: str) -> bool:
    """Return whether ``key`` names a credential, as a JSON key or an env-var name.

    The one key-name rule: :func:`is_secret_structured_key` applies it to
    structured payloads and :func:`mergecraft.utils.secrets.is_sensitive_env_name`
    to environment variables, so both agree on ``DB_PASSWORD``,
    ``OPENAI_API_KEY`` and ``aws_secret_access_key``.
    """
    normalized = _normalize_structured_key(key)
    if normalized in _DENY_KEY_SET or SECRET_KEY_RE.match(normalized):
        return True
    words = _key_words(key)
    if not words:
        return False
    if words[-1] in _CREDENTIAL_LAST_WORDS:
        return True
    return len(words) >= 2 and words[-1] == "key" and words[-2] in _CREDENTIAL_KEY_QUALIFIERS


def is_secret_structured_key(key: str) -> bool:
    """Return whether ``key`` names a credential field in structured payloads."""
    return is_credential_key_name(key)


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
    "is_credential_key_name",
    "is_secret_structured_key",
    "redact_structured_value",
]
