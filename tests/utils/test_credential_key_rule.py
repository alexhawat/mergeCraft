"""One key-name rule for structured redaction and the env filter (W1.1-5)."""

from __future__ import annotations

import pytest

from mergecraft.analyzers.redact import redact_analyzer_output
from mergecraft.redaction_sentinel import REDACTION_SENTINEL
from mergecraft.redaction_structured import is_credential_key_name, is_secret_structured_key
from mergecraft.utils.secrets import is_sensitive_env_name

_CREDENTIAL_KEYS = [
    "DB_PASSWORD",
    "OPENAI_API_KEY",
    "aws_secret_access_key",
    "webhook_secret",
    "session_cookie",
    "GITHUB_TOKEN",
    "clientSecret",
    "apiKey",
    "x-api-key",
    "private_key",
    "password",
    "passwd",
    "token",
    "db_passphrase",
    "SERVICE_CREDENTIAL",
]

_ORDINARY_KEYS = [
    "ruleId",
    "cache_key",
    "sort_key",
    "correlation_key",
    "input_tokens",
    "max_tokens",
    "token_count",
    "secret_scanning_enabled",
    "PATH",
    "PWD",
    "SSH_AUTH_SOCK",
    "ACTIONS_ID_TOKEN_REQUEST_URL",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "key",
]


@pytest.mark.parametrize("key", _CREDENTIAL_KEYS, ids=_CREDENTIAL_KEYS)
def test_credential_key_names_are_classified_alike_everywhere(key: str) -> None:
    assert is_credential_key_name(key)
    assert is_secret_structured_key(key)
    assert is_sensitive_env_name(key)


@pytest.mark.parametrize("key", _ORDINARY_KEYS, ids=_ORDINARY_KEYS)
def test_ordinary_key_names_are_not_structured_credentials(key: str) -> None:
    assert not is_credential_key_name(key)
    assert not is_secret_structured_key(key)


_ORDINARY_ENV_NAMES = [key for key in _ORDINARY_KEYS if not key.endswith("_key")]


@pytest.mark.parametrize("key", _ORDINARY_ENV_NAMES, ids=_ORDINARY_ENV_NAMES)
def test_ordinary_env_names_still_pass_the_env_filter(key: str) -> None:
    assert not is_sensitive_env_name(key)


def test_env_filter_keeps_its_broader_key_suffix() -> None:
    """Withholding an env var is the safe error; ``*_KEY`` stays sensitive there."""
    assert is_sensitive_env_name("CACHE_KEY")
    assert not is_secret_structured_key("cache_key")


@pytest.mark.parametrize("key", _CREDENTIAL_KEYS, ids=_CREDENTIAL_KEYS)
def test_low_entropy_values_under_credential_keys_are_redacted_in_json(key: str) -> None:
    raw = f'{{"{key}": "proj123", "ruleId": "B101"}}'

    out = redact_analyzer_output(raw, tool_id="x")

    assert "proj123" not in out
    assert REDACTION_SENTINEL in out
    assert '"ruleId": "B101"' in out
