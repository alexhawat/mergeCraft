"""Normalize environment variable names and sanitize sensitive values."""

from __future__ import annotations

import os

from loguru import logger

from mergecraft.utils.secrets import is_sensitive_env_name, sanitize_secret


def _is_proxy_key(key: str) -> bool:
    """Return True for ``http_proxy``-style names whose lowercase spelling is meaningful."""
    return key.lower().endswith("_proxy")


def normalize_env(environ: dict[str, str] | None = None) -> None:
    """Uppercase env keys and trim/mask sensitive values in-place.

    When ``environ`` is ``None``, mutates ``os.environ``. Conflicts across
    differently-cased keys keep the uppercase value (or the first seen).

    ``*_proxy`` variables are the exception: curl ignores uppercase ``HTTP_PROXY``
    (httpoxy) and several tools read only lowercase ``no_proxy``, so the lowercase
    spelling is never deleted. An uppercase alias is added when absent.
    """
    env: dict[str, str] = os.environ if environ is None else environ  # type: ignore[assignment]  # — os.environ is Environ[str]; compatible with dict[str, str] for read/write mutation

    upper_keys: dict[str, list[str]] = {}
    for key in list(env.keys()):
        upper = key.upper()
        upper_keys.setdefault(upper, []).append(key)

    for upper_key, keys in upper_keys.items():
        if _is_proxy_key(upper_key):
            if upper_key not in env:
                env[upper_key] = env[keys[0]]
            continue

        if len(keys) == 1:
            key = keys[0]
            if key != upper_key:
                env[upper_key] = env[key]
                del env[key]
            continue

        values = [env[k] for k in keys]
        if len(set(values)) > 1:
            logger.warning(
                "env var conflict: {} have different values. using uppercase {}.",
                ", ".join(keys),
                upper_key,
            )

        preferred_key = next((k for k in keys if k == upper_key), keys[0])
        preferred_value = env[preferred_key]

        for key in keys:
            del env[key]
        env[upper_key] = preferred_value

    for key in list(env.keys()):
        if not is_sensitive_env_name(key):
            continue
        value = env.get(key)
        if not isinstance(value, str) or len(value) == 0:
            continue
        sanitized = sanitize_secret(key, value)
        if sanitized is not None:
            env[key] = sanitized
